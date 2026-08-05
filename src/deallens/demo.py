"""Fixture-driven demo: runs the validation + gate + memo path on five
canonical bundles without any API keys or network.

The quote validation and gate classification run live — fixtures supply the
extracted content, and one bundle contains a paraphrased quote that gets
discarded in front of you. Only the network stages (/research, /search,
/extract) and LLM narrative are replaced by fixture data.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import JurisdictionPack, Policy, load_jurisdiction, load_policy
from .gate import apply_severity, classify, coverage, quote_in_content, risk_level
from .models import (
    CATEGORIES,
    Candidate,
    Evidence,
    Finding,
    RetrievalMetrics,
    RetrievalProvenance,
    ScreenResult,
    UsageLedger,
)


def build_result(fixture_path: Path, pack: JurisdictionPack, policy: Policy) -> ScreenResult:
    data = json.loads(fixture_path.read_text())

    findings: list[Finding] = []
    sources_reviewed: dict[str, int] = {}
    for bundle in data["bundles"]:
        candidate = Candidate(**bundle["candidate"])
        candidate.provenance = [
            RetrievalProvenance(
                method="fixture",
                endpoint="search",
                query=candidate.verification_query,
            )
        ]
        sources_reviewed[candidate.category] = (
            sources_reviewed.get(candidate.category, 0) + bundle.get("sources_reviewed", 0)
        )

        evidence: list[Evidence] = []
        for source in bundle.get("sources", []):
            if not quote_in_content(source["quote"], source["content"]):
                continue  # live demonstration: paraphrases do not survive
            evidence.append(
                Evidence(
                    url=source["url"],
                    title=source.get("title", ""),
                    publisher=source["publisher"],
                    published_date=source.get("published_date"),
                    source_tier=pack.tier_for(source["url"]),
                    quote=source["quote"],
                    provenance=[
                        RetrievalProvenance(
                            method="fixture",
                            endpoint="extract",
                            query=candidate.claim,
                            source_url=source["url"],
                        )
                    ],
                )
            )

        finding = classify(
            candidate, evidence, bundle.get("extraction_failures", []), searches_run=2
        )
        finding = apply_severity(finding, policy)
        finding.narrative = bundle.get("narrative", "") if finding.status != "unresolved" else (
            "A potential regulatory reference was discovered, but the underlying "
            "source could not be captured for verification. Human review is required."
        )
        findings.append(finding)

    return ScreenResult(
        target=data["target"],
        domain=data["domain"],
        jurisdiction=data["jurisdiction"],
        company_id=data.get("company_id"),
        risk_level=risk_level(findings),
        findings=findings,
        coverage=coverage(
            findings,
            sources_reviewed,
            {category: 1 for category in CATEGORIES},
        ),
        usage=UsageLedger(),  # fixture run: no credits spent — the point
        retrieval_metrics=RetrievalMetrics(
            baseline_incremental_candidates=len(findings),
            validated_evidence=sum(len(finding.evidence) for finding in findings),
            surfaced_claims=sum(
                finding.status != "rejected" for finding in findings
            ),
        ),
    )


def run_demo(root: Path) -> ScreenResult:
    pack = load_jurisdiction("uk", root=root)
    policy = load_policy(root=root)
    return build_result(root / "fixtures" / "demo_screen.json", pack, policy)
