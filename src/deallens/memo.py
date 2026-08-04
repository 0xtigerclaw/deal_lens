"""Renderers: screening memo (markdown), evidence file (JSON), console summary."""

from __future__ import annotations

import json
from pathlib import Path

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

DISCLAIMER = (
    "This screen is an initial review of public evidence, not a legal or "
    "financial diligence opinion. \"No qualifying public findings\" means the "
    "governed checks completed without a result that met the evidence standard — it "
    "is not a statement that no risk exists."
)


def render_memo(result: ScreenResult) -> str:
    lines: list[str] = [
        "# Acquisition Red-Flag Screen",
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
        lines += ["", "## Rejected as weak or unsupported", ""]
        lines += [
            f"- {f.candidate.claim} — no qualifying source survived verification"
            for f in rejected
        ]

    coverage_issues = [cov for cov in result.coverage if cov.note]
    if coverage_issues:
        lines += ["", "## Pipeline review items", ""]
        lines += [
            f"- {CATEGORY_LABELS[cov.category]}: {cov.note}"
            for cov in coverage_issues
        ]

    lines += [
        "",
        "## Coverage",
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
        "## Run footprint",
        "",
        f"- Tavily credits: {usage.tavily_credits:g} ({by_endpoint})",
        f"- LLM tokens: {usage.llm_input_tokens:,} in / {usage.llm_output_tokens:,} out",
        f"- Wall time: {usage.wall_seconds:.0f}s",
    ]
    if usage.usage_notes:
        lines.append(f"- Usage notes: {'; '.join(usage.usage_notes)}")
    lines.append("")
    return "\n".join(lines)


def _assessment_sentence(result: ScreenResult) -> str:
    statuses = (
        "verified", "reported", "partial", "conflicting", "contradicted",
        "unresolved", "rejected",
    )
    counts = {s: sum(1 for f in result.findings if f.status == s) for s in statuses}
    parts = []
    if counts["verified"]:
        parts.append(f"{counts['verified']} verified red flag(s)")
    if counts["reported"]:
        parts.append(f"{counts['reported']} reported concern(s)")
    if counts["partial"]:
        parts.append(f"{counts['partial']} partially supported claim(s)")
    if counts["conflicting"]:
        parts.append(f"{counts['conflicting']} conflicting claim(s)")
    if counts["unresolved"]:
        parts.append(f"{counts['unresolved']} unresolved check(s)")
    pipeline_issues = sum(bool(cov.note) for cov in result.coverage)
    if pipeline_issues:
        parts.append(f"{pipeline_issues} baseline interpretation issue(s)")
    if not parts:
        return "no findings met the evidence standard."
    return ", ".join(parts) + f"; {counts['rejected']} candidate(s) rejected as weak or unsupported."


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
        f"{counts['rejected']} finding(s) rejected as weak or unsupported",
        "",
        f"Memo: {memo_path}",
        f"Evidence: {json_path}",
        f"Tavily usage: {result.usage.tavily_credits:g} credits",
    ])
    console.print(Panel(body, title="DEALLENS SCREEN COMPLETE", border_style="cyan"))
