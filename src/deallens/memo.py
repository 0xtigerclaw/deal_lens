"""Renderers: investment committee memo, evidence file, and console summary."""

from __future__ import annotations

from html import escape
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel

from .models import CATEGORY_LABELS, Finding, ScreenResult

STATUS_HEADINGS = [
    ("verified", "Verified findings"),
    ("reported", "Reported concerns"),
    ("partial", "Partially supported — review required"),
    ("conflicting", "Conflicting evidence — review required"),
    ("contradicted", "Claims contradicted by qualifying evidence"),
    ("unresolved", "Unresolved checks"),
]

COVERAGE_LABELS = {
    "verified_finding": "Verified finding",
    "reported": "Reported concern",
    "review_required": "Review required",
    "checked_no_finding": "Checked — no qualifying finding",
    "not_checked": "Not independently checked",
}

FINDING_LABELS = {
    "verified": "Verified",
    "reported": "Reported concern",
    "partial": "Partial support",
    "conflicting": "Conflicting evidence",
    "contradicted": "Contradicted",
    "unresolved": "Unresolved",
    "rejected": "Not substantiated",
}

DISCLAIMER = (
    "This memo is an initial review of public evidence, not a legal or "
    "financial diligence opinion. \"No qualifying public findings\" means the "
    "governed checks completed without a result that met the evidence standard — it "
    "is not a statement that no risk exists."
)


def render_memo(result: ScreenResult) -> str:
    lines: list[str] = [
        "# Investment Committee Diligence Memo",
        "",
        f"Target: {result.target}",
        f"Domain: {result.domain}",
        f"Legal entity ID: {result.company_id or 'Not supplied'}",
        f"Jurisdiction: {result.jurisdiction}",
        f"Generated: {result.generated_at:%d %B %Y}",
        "",
        "## Executive assessment",
        "",
        f"**{result.risk_level}** — {_assessment_sentence(result)}",
        "",
        DISCLAIMER,
    ]

    for status, heading in STATUS_HEADINGS:
        matching = [f for f in result.findings if f.status == status]
        if not matching:
            continue
        lines += ["", f"## {heading}"]
        for finding in matching:
            lines += _finding_block(finding)

    rejected = [f for f in result.findings if f.status == "rejected"]
    if rejected:
        lines += [
            "",
            "## Claims not substantiated by qualifying evidence",
            "",
            "The available sources did not meet the configured evidence standard. "
            "This does not mean these claims are false.",
            "",
        ]
        lines += [
            f"- {f.candidate.claim} — insufficient qualifying evidence"
            for f in rejected
        ]

    coverage_issues = [cov for cov in result.coverage if cov.note]
    if coverage_issues:
        lines += ["", "## Research review items", ""]
        lines += [
            f"- {CATEGORY_LABELS[cov.category]}: {cov.note}"
            for cov in coverage_issues
        ]

    lines += [
        "",
        "## Diligence coverage",
        "",
        "| Check | Status | Checks run | Sources retrieved |",
        "|---|---|---:|---:|",
    ]
    for cov in result.coverage:
        lines.append(
            f"| {CATEGORY_LABELS[cov.category]} | {COVERAGE_LABELS[cov.status]} "
            f"| {cov.checks_run} | {cov.sources_reviewed} |"
        )

    usage = result.usage
    by_endpoint = ", ".join(
        f"{name} {credits:g}" for name, credits in sorted(usage.credits_by_endpoint.items())
    ) or "n/a"
    lines += [
        "",
        "## Research footprint",
        "",
        f"- Tavily credits: {usage.tavily_credits:g} ({by_endpoint})",
        f"- LLM tokens: {usage.llm_input_tokens:,} in / {usage.llm_output_tokens:,} out",
        f"- Wall time: {usage.wall_seconds:.0f}s",
    ]
    if usage.usage_notes:
        lines.append(f"- Usage notes: {'; '.join(usage.usage_notes)}")
    lines.append("")
    return "\n".join(lines)


_PDF_TEXT_REPLACEMENTS = str.maketrans(
    {
        "\u00a0": " ",
        "\u202f": " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
    }
)


def _pdf_plain(value: object) -> str:
    return str(value).translate(_PDF_TEXT_REPLACEMENTS)


def _pdf_text(value: object) -> str:
    """Normalize unsupported typography and escape ReportLab paragraph markup."""
    return escape(_pdf_plain(value), quote=True)


def _register_pdf_fonts() -> None:
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_root = Path(reportlab.__file__).with_name("fonts")
    registered = set(pdfmetrics.getRegisteredFontNames())
    fonts = {
        "DealLensSans": "Vera.ttf",
        "DealLensSansBold": "VeraBd.ttf",
        "DealLensSansItalic": "VeraIt.ttf",
    }
    for name, filename in fonts.items():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, font_root / filename))


def pdf_filename(result: ScreenResult) -> str:
    slug = "".join(
        character if character.isascii() and character.isalnum() else "-"
        for character in result.target.lower()
    ).strip("-")
    slug = "-".join(part for part in slug.split("-") if part) or "target"
    return f"{slug}-{result.generated_at:%Y-%m-%d}-ic-diligence-memo.pdf"


def render_pdf(result: ScreenResult) -> bytes:
    """Render a polished, paginated IC diligence memo as PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    _register_pdf_fonts()
    ink = colors.HexColor("#171812")
    muted = colors.HexColor("#66675f")
    line = colors.HexColor("#d8d4ca")
    paper = colors.HexColor("#f5f2e9")
    soft = colors.HexColor("#ebe7dc")
    signal = colors.HexColor("#a63d2b")
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=f"{result.target} - Investment Committee Diligence Memo",
        author="DealLens",
        subject="Evidence-backed acquisition intelligence",
    )
    content_width = A4[0] - document.leftMargin - document.rightMargin

    eyebrow = ParagraphStyle(
        "DealLensEyebrow",
        fontName="DealLensSansBold",
        fontSize=7.5,
        leading=10,
        textColor=signal,
        spaceAfter=4 * mm,
        uppercase=True,
        tracking=1.2,
    )
    title = ParagraphStyle(
        "DealLensTitle",
        fontName="DealLensSansBold",
        fontSize=25,
        leading=30,
        textColor=ink,
        spaceAfter=3 * mm,
    )
    subtitle = ParagraphStyle(
        "DealLensSubtitle",
        fontName="DealLensSans",
        fontSize=9,
        leading=13,
        textColor=muted,
        spaceAfter=7 * mm,
    )
    heading = ParagraphStyle(
        "DealLensHeading",
        fontName="DealLensSansBold",
        fontSize=14,
        leading=18,
        textColor=ink,
        spaceBefore=7 * mm,
        spaceAfter=3 * mm,
        keepWithNext=True,
    )
    finding_title = ParagraphStyle(
        "DealLensFindingTitle",
        fontName="DealLensSansBold",
        fontSize=10.5,
        leading=15,
        textColor=ink,
        spaceAfter=2.5 * mm,
        keepWithNext=True,
    )
    body = ParagraphStyle(
        "DealLensBody",
        fontName="DealLensSans",
        fontSize=8.5,
        leading=13,
        textColor=ink,
        spaceAfter=2.5 * mm,
    )
    small = ParagraphStyle(
        "DealLensSmall",
        fontName="DealLensSans",
        fontSize=7,
        leading=10,
        textColor=muted,
    )
    small_bold = ParagraphStyle(
        "DealLensSmallBold",
        parent=small,
        fontName="DealLensSansBold",
        textColor=ink,
    )
    small_on_dark = ParagraphStyle(
        "DealLensSmallOnDark",
        parent=small,
        fontName="DealLensSansBold",
        textColor=colors.white,
    )
    right_small = ParagraphStyle(
        "DealLensRightSmall",
        parent=small,
        alignment=TA_RIGHT,
    )
    metric_value = ParagraphStyle(
        "DealLensMetricValue",
        fontName="DealLensSansBold",
        fontSize=15,
        leading=18,
        textColor=ink,
        alignment=TA_LEFT,
    )
    risk_value = ParagraphStyle(
        "DealLensRiskValue",
        fontName="DealLensSansBold",
        fontSize=15,
        leading=19,
        textColor=colors.white,
    )
    assessment = ParagraphStyle(
        "DealLensAssessment",
        fontName="DealLensSans",
        fontSize=9,
        leading=14,
        textColor=ink,
    )
    quote = ParagraphStyle(
        "DealLensQuote",
        fontName="DealLensSansItalic",
        fontSize=7.5,
        leading=11,
        textColor=ink,
    )

    def page_frame(canvas, doc) -> None:
        canvas.saveState()
        canvas.setTitle(f"{result.target} - Investment Committee Diligence Memo")
        canvas.setAuthor("DealLens")
        canvas.setStrokeColor(line)
        canvas.setLineWidth(0.5)
        canvas.line(document.leftMargin, A4[1] - 13 * mm, A4[0] - document.rightMargin, A4[1] - 13 * mm)
        canvas.setFont("DealLensSansBold", 6.5)
        canvas.setFillColor(signal)
        canvas.drawString(document.leftMargin, A4[1] - 9 * mm, "DEALLENS / IC DILIGENCE")
        canvas.setFillColor(muted)
        canvas.setFont("DealLensSans", 6.5)
        canvas.drawRightString(A4[0] - document.rightMargin, A4[1] - 9 * mm, _pdf_plain(result.target))
        canvas.line(document.leftMargin, 13 * mm, A4[0] - document.rightMargin, 13 * mm)
        canvas.setFont("DealLensSans", 6.5)
        canvas.drawString(document.leftMargin, 8.5 * mm, "CONFIDENTIAL - PUBLIC-SOURCE DILIGENCE")
        canvas.drawRightString(A4[0] - document.rightMargin, 8.5 * mm, f"PAGE {doc.page}")
        canvas.restoreState()

    story: list = [
        Spacer(1, 4 * mm),
        Paragraph("INVESTMENT COMMITTEE DILIGENCE MEMO", eyebrow),
        Paragraph(_pdf_text(result.target), title),
        Paragraph(
            f"{_pdf_text(result.domain)} &nbsp;&nbsp;/&nbsp;&nbsp; "
            f"{_pdf_text(result.jurisdiction)} &nbsp;&nbsp;/&nbsp;&nbsp; "
            f"Prepared {_pdf_text(result.generated_at.strftime('%d %B %Y'))}",
            subtitle,
        ),
    ]

    metadata = [
        [
            Paragraph("DOMAIN", small),
            Paragraph("LEGAL ENTITY ID", small),
            Paragraph("JURISDICTION", small),
        ],
        [
            Paragraph(_pdf_text(result.domain), small_bold),
            Paragraph(_pdf_text(result.company_id or "Not supplied"), small_bold),
            Paragraph(_pdf_text(result.jurisdiction), small_bold),
        ],
    ]
    metadata_table = Table(metadata, colWidths=[content_width / 3] * 3)
    metadata_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), paper),
                ("BOX", (0, 0), (-1, -1), 0.5, line),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, line),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([metadata_table, Spacer(1, 6 * mm)])

    assessment_table = Table(
        [
            [
                [
                    Paragraph("ACQUISITION ASSESSMENT", small_on_dark),
                    Spacer(1, 2 * mm),
                    Paragraph(_pdf_text(result.risk_level), risk_value),
                ],
                [
                    Paragraph("EVIDENCE SUMMARY", small),
                    Spacer(1, 1.5 * mm),
                    Paragraph(_pdf_text(_assessment_sentence(result)), assessment),
                ],
            ]
        ],
        colWidths=[content_width * 0.34, content_width * 0.66],
    )
    assessment_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), ink),
                ("BACKGROUND", (1, 0), (1, 0), soft),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, line),
                ("LEFTPADDING", (0, 0), (-1, -1), 11),
                ("RIGHTPADDING", (0, 0), (-1, -1), 11),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([assessment_table, Spacer(1, 5 * mm)])

    counts = {
        status: sum(finding.status == status for finding in result.findings)
        for status in FINDING_LABELS
    }
    metrics = [
        (counts["verified"], "VERIFIED"),
        (counts["reported"], "REPORTED"),
        (
            counts["partial"] + counts["conflicting"] + counts["contradicted"],
            "NEEDS REVIEW",
        ),
        (counts["unresolved"], "UNRESOLVED"),
        (counts["rejected"], "NOT SUBSTANTIATED"),
    ]
    metric_cells = [
        [Paragraph(str(value), metric_value), Paragraph(label, small)]
        for value, label in metrics
    ]
    metric_table = Table([metric_cells], colWidths=[content_width / 5] * 5)
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), paper),
                ("BOX", (0, 0), (-1, -1), 0.5, line),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, line),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(metric_table)

    surfaced = [finding for finding in result.findings if finding.status != "rejected"]
    story.append(Paragraph("Findings for IC review", heading))
    if not surfaced:
        story.append(Paragraph("No finding met the configured evidence threshold.", body))
    for index, finding in enumerate(surfaced, start=1):
        category = CATEGORY_LABELS.get(finding.candidate.category, finding.candidate.category)
        severity = f" / {finding.severity.upper()} SEVERITY" if finding.severity else ""
        label = f"{index:02d} / {FINDING_LABELS[finding.status].upper()} / {category.upper()}{severity}"
        header = [
            Paragraph(_pdf_text(label), small_bold),
            Spacer(1, 1.5 * mm),
            Paragraph(_pdf_text(finding.candidate.claim), finding_title),
        ]
        if finding.narrative:
            header.append(Paragraph(_pdf_text(finding.narrative), body))
        if len(finding.candidate.assertions) > 1:
            assertion_rows = []
            for assertion_index, assertion in enumerate(finding.candidate.assertions):
                assertion_rows.append(
                    [
                        Paragraph(f"A{assertion_index}", small_bold),
                        Paragraph(_pdf_text(assertion), small),
                    ]
                )
            assertion_table = Table(
                assertion_rows,
                colWidths=[12 * mm, content_width - 12 * mm],
            )
            assertion_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), soft),
                        ("BOX", (0, 0), (-1, -1), 0.4, line),
                        ("INNERGRID", (0, 0), (-1, -1), 0.4, line),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            header.extend([assertion_table, Spacer(1, 2.5 * mm)])

        story.append(KeepTogether(header))

        for evidence in finding.evidence:
            quote_table = Table(
                [[Paragraph(f'"{_pdf_text(evidence.quote)}"', quote)]],
                colWidths=[content_width],
            )
            quote_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), paper),
                        ("LINEBEFORE", (0, 0), (0, -1), 2, signal),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            publisher = evidence.publisher or urlparse(evidence.url).netloc or "Source"
            source_bits = [
                f'<link href="{_pdf_text(evidence.url)}" color="#2f6d55"><b>{_pdf_text(publisher)}</b></link>',
                _pdf_text(evidence.source_tier.replace("_", " ").title()),
            ]
            if evidence.published_date:
                source_bits.append(_pdf_text(evidence.published_date))
            story.extend(
                [
                    quote_table,
                    Spacer(1, 1.5 * mm),
                    Paragraph(" / ".join(source_bits), small),
                    Spacer(1, 2.5 * mm),
                ]
            )

        failures = [
            *(f"Could not capture: {url}" for url in finding.extraction_failures),
            *finding.processing_failures,
        ]
        for failure in failures:
            story.append(Paragraph(f"RESEARCH NOTE / {_pdf_text(failure)}", small))
        story.extend(
            [
                Spacer(1, 3 * mm),
                HRFlowable(width="100%", thickness=0.5, color=line),
                Spacer(1, 4 * mm),
            ]
        )

    rejected = [finding for finding in result.findings if finding.status == "rejected"]
    if rejected:
        story.append(Paragraph("Claims not substantiated by qualifying evidence", heading))
        story.append(
            Paragraph(
                "The available sources did not meet the configured evidence standard. "
                "This does not mean these claims are false.",
                body,
            )
        )
        for finding in rejected:
            category = CATEGORY_LABELS.get(finding.candidate.category, finding.candidate.category)
            story.append(
                Paragraph(
                    f"<b>{_pdf_text(category)}</b> - {_pdf_text(finding.candidate.claim)}",
                    body,
                )
            )

    story.append(Paragraph("Diligence coverage", heading))
    coverage_rows = [
        [
            Paragraph("RISK AREA", small_on_dark),
            Paragraph("STATUS", small_on_dark),
            Paragraph("CHECKS", small_on_dark),
            Paragraph("SOURCES", small_on_dark),
        ]
    ]
    for item in result.coverage:
        coverage_rows.append(
            [
                Paragraph(_pdf_text(CATEGORY_LABELS.get(item.category, item.category)), small_bold),
                Paragraph(_pdf_text(COVERAGE_LABELS.get(item.status, item.status)), small),
                Paragraph(str(item.checks_run), right_small),
                Paragraph(str(item.sources_reviewed), right_small),
            ]
        )
    coverage_table = Table(
        coverage_rows,
        repeatRows=1,
        colWidths=[content_width * 0.34, content_width * 0.42, content_width * 0.12, content_width * 0.12],
    )
    coverage_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ink),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, paper]),
                ("BOX", (0, 0), (-1, -1), 0.5, line),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, line),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(coverage_table)
    for item in result.coverage:
        if item.note:
            story.append(
                Paragraph(
                    f"<b>{_pdf_text(CATEGORY_LABELS.get(item.category, item.category))}:</b> {_pdf_text(item.note)}",
                    small,
                )
            )

    story.append(Paragraph("Research footprint", heading))
    usage = result.usage
    footprint = Table(
        [
            [Paragraph("TAVILY", small), Paragraph(f"{usage.tavily_credits:g} credits", small_bold)],
            [Paragraph("KIMI TOKENS", small), Paragraph(f"{usage.llm_input_tokens:,} input / {usage.llm_output_tokens:,} output", small_bold)],
            [Paragraph("WALL TIME", small), Paragraph(f"{usage.wall_seconds:.0f} seconds", small_bold)],
        ],
        colWidths=[content_width * 0.26, content_width * 0.74],
    )
    footprint.setStyle(
        TableStyle(
            [
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [paper, colors.white]),
                ("BOX", (0, 0), (-1, -1), 0.5, line),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, line),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            footprint,
            Spacer(1, 6 * mm),
            HRFlowable(width="100%", thickness=0.5, color=line),
            Spacer(1, 3 * mm),
            Paragraph(_pdf_text(DISCLAIMER), small),
        ]
    )
    document.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return buffer.getvalue()


def _assessment_sentence(result: ScreenResult) -> str:
    statuses = (
        "verified", "reported", "partial", "conflicting", "contradicted",
        "unresolved", "rejected",
    )
    counts = {s: sum(1 for f in result.findings if f.status == s) for s in statuses}
    def phrase(value: int, singular: str, plural: str | None = None) -> str:
        return f"{value} {singular if value == 1 else (plural or singular + 's')}"

    parts: list[str] = []
    if counts["verified"]:
        parts.append(phrase(counts["verified"], "verified red flag"))
    if counts["reported"]:
        parts.append(phrase(counts["reported"], "reported concern"))
    if counts["partial"]:
        parts.append(phrase(counts["partial"], "partially supported claim"))
    if counts["conflicting"]:
        parts.append(phrase(counts["conflicting"], "conflicting claim"))
    if counts["contradicted"]:
        parts.append(phrase(counts["contradicted"], "contradicted claim"))
    if counts["unresolved"]:
        parts.append(phrase(counts["unresolved"], "unresolved check"))
    pipeline_issues = sum(bool(cov.note) for cov in result.coverage)
    if pipeline_issues:
        parts.append(phrase(pipeline_issues, "baseline interpretation issue"))
    if not parts:
        return "no findings met the evidence standard."
    if len(parts) == 1:
        summary = parts[0]
    elif len(parts) == 2:
        summary = " and ".join(parts)
    else:
        summary = ", ".join(parts[:-1]) + f", and {parts[-1]}"
    not_substantiated = phrase(counts["rejected"], "candidate claim")
    return f"{summary}; {not_substantiated} did not meet the evidence standard."


def _finding_block(finding: Finding) -> list[str]:
    severity = f" — {finding.severity.capitalize()}" if finding.severity else ""
    lines = ["", f"### {finding.candidate.claim}{severity}", ""]
    if len(finding.candidate.assertions) > 1:
        lines += ["Assertions required for this claim:", ""]
        lines += [
            f"- A{index}: {assertion}"
            for index, assertion in enumerate(finding.candidate.assertions)
        ]
        lines.append("")
    if finding.narrative:
        lines += [finding.narrative, ""]
    for e in finding.evidence:
        tier = {"primary": "Primary source", "credible_secondary": "Source",
                "other": "Uncorroborated source"}[e.source_tier]
        dated = f", {e.published_date}" if e.published_date else ""
        relationships = []
        if e.supports_assertions:
            relationships.append(
                "supports " + ", ".join(f"A{i}" for i in e.supports_assertions)
            )
        if e.contradicts_assertions:
            relationships.append(
                "contradicts "
                + ", ".join(f"A{i}" for i in e.contradicts_assertions)
            )
        relationship = f" — {'; '.join(relationships)}" if relationships else ""
        lines += [
            f'> "{e.quote}"',
            "",
            f"{tier}: [{e.publisher}]({e.url}){dated}{relationship}",
            "",
        ]
    if finding.extraction_failures:
        lines += [
            "Could not capture: " + ", ".join(finding.extraction_failures),
            "",
        ]
    if finding.processing_failures:
        lines += [
            "Processing issue: " + "; ".join(finding.processing_failures),
            "",
        ]
    if finding.policy_triggers:
        lines += [f"Policy triggered: {', '.join(finding.policy_triggers)}", ""]
    return lines


def write_outputs(result: ScreenResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in result.target.lower()).strip("-")
    base = out_dir / f"{slug}-{result.generated_at:%Y-%m-%d}"
    memo_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    memo_path.write_text(render_memo(result))
    json_path.write_text(json.dumps(result.model_dump(mode="json"), indent=2))
    return memo_path, json_path


def print_summary(result: ScreenResult, memo_path: Path, json_path: Path) -> None:
    console = Console()
    statuses = (
        "verified", "reported", "partial", "conflicting", "contradicted",
        "unresolved", "rejected",
    )
    counts = {s: sum(1 for f in result.findings if f.status == s) for s in statuses}
    pipeline_issues = sum(bool(cov.note) for cov in result.coverage)
    body = "\n".join([
        f"Target: {result.target}",
        f"Risk level: [bold]{result.risk_level}[/bold]",
        "",
        f"{counts['verified']} verified red flag(s)",
        f"{counts['reported']} reported concern(s)",
        f"{counts['partial']} partially supported claim(s)",
        f"{counts['conflicting']} conflicting claim(s)",
        f"{counts['unresolved']} unresolved check(s)",
        f"{pipeline_issues} baseline interpretation issue(s)",
        f"{counts['rejected']} candidate claim(s) not substantiated by qualifying evidence",
        "",
        f"Memo: {memo_path}",
        f"Evidence: {json_path}",
        f"Tavily usage: {result.usage.tavily_credits:g} credits",
    ])
    console.print(Panel(body, title="DEALLENS IC MEMO READY", border_style="cyan"))
