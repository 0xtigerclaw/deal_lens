"""Typed core of DealLens. Every pipeline boundary passes one of these models."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Category = Literal["leadership", "regulatory", "cyber", "distress"]
CATEGORIES: tuple[Category, ...] = ("leadership", "regulatory", "cyber", "distress")

CATEGORY_LABELS: dict[str, str] = {
    "leadership": "Leadership and ownership",
    "regulatory": "Regulatory and litigation",
    "cyber": "Cybersecurity",
    "distress": "Financial distress",
}

SourceTier = Literal["primary", "credible_secondary", "other"]
FindingStatus = Literal[
    "verified",
    "reported",
    "partial",
    "conflicting",
    "contradicted",
    "unresolved",
    "rejected",
]
Severity = Literal["low", "medium", "high"]

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)"
)
_DATE_PATTERNS = (
    re.compile(rf"\b\d{{1,2}}\s+{_MONTH}\s+(?:19|20)\d{{2}}\b", re.I),
    re.compile(rf"\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+(?:19|20)\d{{2}}\b", re.I),
    re.compile(rf"\b{_MONTH}\s+(?:19|20)\d{{2}}\b", re.I),
    re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/](?:19|20)\d{2}\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),
)
_QUANTITY_PATTERNS = (
    re.compile(
        r"(?:[$£€]\s?\d[\d,.]*(?:\s?(?:m|bn|million|billion))?)",
        re.I,
    ),
    re.compile(
        r"\b\d[\d,.]*\s?(?:%|percent|million|billion|employees|staff|jobs)\b",
        re.I,
    ),
)


def _material_claim_anchors(claim: str) -> list[tuple[str, str]]:
    """Return dates and quantities that assertion decomposition may not drop.

    The LLM is free to paraphrase prose, but a weaker assertion set must never
    silently erase an exact date or quantity displayed in the original claim.
    Longest date patterns win so ``7 April 2025`` is one anchor, not a date and
    a second standalone year.
    """
    occupied: list[tuple[int, int]] = []
    anchors: list[tuple[str, str]] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(claim):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            anchors.append((match.group(0), "date"))
    for pattern in _QUANTITY_PATTERNS:
        for match in pattern.finditer(claim):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            anchors.append((match.group(0), "quantity"))
    return anchors


class Candidate(BaseModel):
    """A red-flag hypothesis produced by discovery. Never trusted, only tested."""

    category: Category
    claim: str
    date: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    verification_query: str
    assertions: list[str] = Field(
        default_factory=list,
        description="Atomic factual assertions that together make up the claim.",
    )

    @model_validator(mode="after")
    def complete_assertions(self) -> "Candidate":
        if not self.assertions:
            self.assertions = [self.claim]
        assertion_text = " ".join(self.assertions).casefold()
        for anchor, kind in _material_claim_anchors(self.claim):
            if anchor.casefold() in assertion_text:
                continue
            if kind == "date":
                assertion = f"The claimed event occurred on {anchor}."
            else:
                assertion = f"The claim includes the reported quantity {anchor}."
            self.assertions.append(assertion)
            assertion_text += " " + assertion.casefold()
        return self


class Evidence(BaseModel):
    """One captured source. `quote` must occur verbatim in the extracted page
    content — capture.py enforces this before an Evidence object is created."""

    url: str
    title: str = ""
    publisher: str = ""  # registrable domain, e.g. "thegazette.co.uk"
    published_date: str | None = None
    source_tier: SourceTier
    quote: str
    supports_assertions: list[int] = Field(default_factory=lambda: [0])
    contradicts_assertions: list[int] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Finding(BaseModel):
    candidate: Candidate
    status: FindingStatus
    severity: Severity | None = None
    policy_triggers: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    extraction_failures: list[str] = Field(default_factory=list)
    processing_failures: list[str] = Field(default_factory=list)
    searches_run: int = 0
    narrative: str = ""


class CategoryCoverage(BaseModel):
    category: Category
    status: Literal[
        "verified_finding",
        "reported",
        "review_required",
        "checked_no_finding",
        "not_checked",
    ]
    sources_reviewed: int = 0
    checks_run: int = 0
    note: str | None = None


class UsageLedger(BaseModel):
    tavily_credits: float = 0.0
    credits_by_endpoint: dict[str, float] = Field(default_factory=dict)
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    wall_seconds: float = 0.0
    usage_complete: bool = True
    usage_notes: list[str] = Field(default_factory=list)

    def add_credits(self, endpoint: str, credits: float) -> None:
        self.tavily_credits += credits
        self.credits_by_endpoint[endpoint] = (
            self.credits_by_endpoint.get(endpoint, 0.0) + credits
        )


RiskLevel = Literal[
    "REVIEW REQUIRED", "PROCEED WITH NOTES", "NO QUALIFYING FINDINGS"
]


class ScreenResult(BaseModel):
    target: str
    domain: str
    jurisdiction: str
    company_id: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    risk_level: RiskLevel
    findings: list[Finding] = Field(default_factory=list)
    coverage: list[CategoryCoverage] = Field(default_factory=list)
    usage: UsageLedger = Field(default_factory=UsageLedger)
