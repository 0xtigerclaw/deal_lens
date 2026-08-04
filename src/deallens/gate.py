"""The evidence gate: deterministic rules that decide what counts as verified.

Discovery (an LLM inside /research) proposes candidates; this module decides
their status. The model never grades its own homework.

    VERIFIED    every atomic assertion has >=1 primary source, or >=2
                credible-secondary publishers
    REPORTED    every assertion has evidence, but at least one has only one
                credible-secondary publisher
    PARTIAL     only some assertions meet an evidence threshold
    CONFLICTING qualifying evidence both supports and contradicts the claim
    CONTRADICTED qualifying evidence directly refutes the claim
    UNRESOLVED  no qualifying evidence, but extraction failed or was blocked
                somewhere along the way (a human must look)
    REJECTED    searches completed; only unsupported or low-tier material
    NO FINDING  category-level: discovery produced no candidates at all
                (rendered as "no qualifying public findings", never "cleared")
"""

from __future__ import annotations

import re

from .config import Policy
from .models import (
    CATEGORIES,
    Candidate,
    CategoryCoverage,
    Evidence,
    Finding,
    RiskLevel,
    Severity,
)

_SEVERITY_ORDER: list[Severity] = ["low", "medium", "high"]

# Extracted pages use curly punctuation inconsistently; quotes are compared
# after normalizing these variants and collapsing whitespace.
_PUNCT_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"',
                            "”": '"', "–": "-", "—": "-",
                            " ": " "})


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_PUNCT_MAP)).strip()


def quote_in_content(quote: str, content: str) -> bool:
    """True iff the quote occurs verbatim in the content, modulo whitespace
    and punctuation-variant normalization. Empty quotes never validate."""
    q = normalize_text(quote)
    return bool(q) and q in normalize_text(content)


def _distinct_domains(evidence: list[Evidence]) -> set[str]:
    return {e.publisher for e in evidence if e.publisher}


def _assertion_level(
    evidence: list[Evidence], assertion_index: int, relationship: str
) -> str:
    matching = [
        item
        for item in evidence
        if assertion_index in getattr(item, relationship)
    ]
    if any(item.source_tier == "primary" for item in matching):
        return "verified"
    secondary = [
        item for item in matching if item.source_tier == "credible_secondary"
    ]
    if len(_distinct_domains(secondary)) >= 2:
        return "verified"
    if secondary:
        return "reported"
    return "none"


def classify(
    candidate: Candidate,
    evidence: list[Evidence],
    extraction_failures: list[str],
    searches_run: int = 0,
    processing_failures: list[str] | None = None,
) -> Finding:
    """Apply the gate to one candidate. `evidence` must already be
    quote-validated (capture.py discards anything that fails validation)."""
    positive = [
        _assertion_level(evidence, index, "supports_assertions")
        for index in range(len(candidate.assertions))
    ]
    negative = [
        _assertion_level(evidence, index, "contradicts_assertions")
        for index in range(len(candidate.assertions))
    ]
    has_positive = any(level != "none" for level in positive)
    has_negative = any(level != "none" for level in negative)

    if has_positive and has_negative:
        status = "conflicting"
    elif has_negative:
        status = "contradicted"
    elif positive and all(level == "verified" for level in positive):
        status = "verified"
    elif positive and all(level in ("verified", "reported") for level in positive):
        status = "reported"
    elif has_positive:
        status = "partial"
    elif extraction_failures or processing_failures:
        status = "unresolved"
    else:
        status = "rejected"

    return Finding(
        candidate=candidate,
        status=status,
        evidence=evidence,
        extraction_failures=extraction_failures,
        processing_failures=processing_failures or [],
        searches_run=searches_run,
    )


def apply_severity(finding: Finding, policy: Policy) -> Finding:
    """Attach severity from the policy file. Only findings that will surface
    in the memo body (verified/reported) carry severity."""
    if finding.status not in ("verified", "reported", "partial", "conflicting"):
        return finding

    rule = policy.rules.get(finding.candidate.category)
    if rule is None:
        finding.severity = "medium"
        return finding

    haystack = " ".join(
        [finding.candidate.claim, *(e.quote for e in finding.evidence)]
    ).lower()
    triggers = [kw for kw in rule.escalate_when if kw.lower() in haystack]

    level = _SEVERITY_ORDER.index(rule.base)
    if triggers:
        level = min(level + 1, len(_SEVERITY_ORDER) - 1)

    finding.severity = _SEVERITY_ORDER[level]
    finding.policy_triggers = triggers
    return finding


def coverage(
    findings: list[Finding],
    sources_reviewed: dict[str, int] | None = None,
    checks_run: dict[str, int] | None = None,
    check_failures: dict[str, str] | None = None,
) -> list[CategoryCoverage]:
    reviewed = sources_reviewed or {}
    checks = checks_run or {}
    failures = check_failures or {}
    out: list[CategoryCoverage] = []
    for category in CATEGORIES:
        in_cat = [f for f in findings if f.candidate.category == category]
        if category in failures:
            status = "review_required"
        elif any(f.status == "verified" for f in in_cat):
            status = "verified_finding"
        elif any(
            f.status in ("partial", "conflicting", "unresolved") for f in in_cat
        ):
            status = "review_required"
        elif any(f.status == "reported" for f in in_cat):
            status = "reported"
        elif checks.get(category, 0) > 0:
            status = "checked_no_finding"
        else:
            status = "not_checked"
        out.append(
            CategoryCoverage(
                category=category,
                status=status,
                sources_reviewed=reviewed.get(category, 0),
                checks_run=checks.get(category, 0),
                note=failures.get(category),
            )
        )
    return out


def risk_level(
    findings: list[Finding], pipeline_review_required: bool = False
) -> RiskLevel:
    """Overall triage verdict.

    REVIEW REQUIRED    any verified finding, any unresolved check (a human
                       must look — that is what unresolved means), or a
                       high-severity reported concern
    PROCEED WITH NOTES reported concerns only
    NO QUALIFYING FINDINGS  all categories were checked and nothing surfaced
    """
    if pipeline_review_required or any(
        f.status in ("verified", "partial", "conflicting", "unresolved")
        for f in findings
    ):
        return "REVIEW REQUIRED"
    if any(f.status == "reported" and f.severity == "high" for f in findings):
        return "REVIEW REQUIRED"
    if any(f.status == "reported" for f in findings):
        return "PROCEED WITH NOTES"
    return "NO QUALIFYING FINDINGS"
