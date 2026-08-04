"""Orchestration: discover → verify → capture → gate → memo inputs.

Deterministic control flow — the sequence of Tavily calls never depends on
model output beyond the candidates themselves.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from langsmith import get_current_run_tree, traceable

from .capture import capture
from .config import JurisdictionPack, Policy
from .discover import (
    baseline_checks,
    discover,
    discover_from_baseline,
    merge_candidates,
)
from .gate import apply_severity, classify, coverage, risk_level
from .llm import LLM
from .models import Finding, ScreenResult, UsageLedger
from .tavily_client import Tavily
from .verify import pick_extraction_urls, verify

ProgressCallback = Callable[[str, str, int], None]

NARRATIVE_PROMPT = """Write 2-3 factual sentences summarizing this finding for an
acquisition screening memo. State only what the quoted evidence supports; name
the sources by publisher. No speculation, no advice, no adjectives like
"concerning".

Claim: {claim}
Status: {status}
Evidence:
{evidence}"""

UNRESOLVED_NARRATIVE = (
    "A potential {category} reference was discovered, but the underlying "
    "source could not be captured for verification. Human review is required."
)


@traceable(
    name="deallens.screen",
    run_type="chain",
    tags=["production-screen", "governed-evidence", "nebius-kimi-k3"],
    metadata={
        "pipeline_version": "0.2.0",
        "model_provider": "Nebius Token Factory",
        "model_family": "Kimi K3",
        "retrieval_provider": "Tavily",
    },
)
def run_screen(
    *,
    company: str,
    domain: str,
    jurisdiction_pack: JurisdictionPack,
    policy: Policy,
    company_id: str | None = None,
    tavily: Tavily | None = None,
    llm: LLM | None = None,
    progress: ProgressCallback | None = None,
) -> ScreenResult:
    started = time.monotonic()
    run_tree = get_current_run_tree()
    if run_tree is not None:
        run_tree.add_metadata(
            {
                "target": company,
                "domain": domain,
                "company_id_supplied": bool(company_id),
                "jurisdiction": jurisdiction_pack.name,
            }
        )
    _notify(progress, "starting", "Starting memo research", 2)
    if tavily is not None:
        ledger = tavily.ledger
    elif llm is not None:
        ledger = llm.ledger
    else:
        ledger = UsageLedger()
    tavily = tavily or Tavily(ledger=ledger)
    tavily.ledger = ledger
    llm = llm or LLM(ledger)
    llm.ledger = ledger

    _notify(progress, "research", "Researching acquisition signals", 8)
    research_candidates = discover(
        tavily, llm, company, domain, jurisdiction_pack.name, company_id
    )
    _notify(
        progress,
        "research",
        f"Found {len(research_candidates)} signals to verify",
        22,
    )
    _notify(progress, "coverage", "Checking four risk areas", 26)
    baseline = baseline_checks(tavily, jurisdiction_pack, company, company_id)
    _notify(progress, "coverage", "Reviewing baseline evidence", 34)
    baseline_candidates, baseline_failures = discover_from_baseline(
        llm, company, baseline
    )
    candidates = merge_candidates(research_candidates, baseline_candidates)
    _notify(
        progress,
        "verification",
        f"Verifying {len(candidates)} candidate findings",
        40,
    )

    findings: list[Finding] = []
    reviewed_urls = {
        category: {result.get("url") for result in results if result.get("url")}
        for category, results in baseline.items()
    }
    checks_run = {category: 1 for category in baseline}
    for index, candidate in enumerate(candidates):
        candidate_progress = 40 + int((index / max(len(candidates), 1)) * 48)
        _notify(
            progress,
            "verification",
            f"Checking {index + 1} of {len(candidates)} · {candidate.category.title()}",
            candidate_progress,
        )
        results, _reviewed, candidate_checks = verify(
            tavily,
            jurisdiction_pack,
            company,
            candidate,
            company_id=company_id,
            baseline_results=baseline.get(candidate.category, []),
        )
        reviewed_urls.setdefault(candidate.category, set()).update(
            result.get("url") for result in results if result.get("url")
        )
        checks_run[candidate.category] = (
            checks_run.get(candidate.category, 0) + candidate_checks
        )
        urls = pick_extraction_urls(
            jurisdiction_pack, candidate, results, company_id=company_id
        )
        evidence, failures, processing_failures = capture(
            tavily, llm, jurisdiction_pack, company, candidate, urls, results
        )
        finding = classify(
            candidate,
            evidence,
            failures,
            searches_run=1 + candidate_checks,
            processing_failures=processing_failures,
        )
        finding = apply_severity(finding, policy)
        finding.narrative = _narrative(llm, finding)
        findings.append(finding)

    _notify(progress, "decision", "Preparing the IC memo", 91)
    ledger.wall_seconds = time.monotonic() - started
    coverage_rows = coverage(
        findings,
        {category: len(urls) for category, urls in reviewed_urls.items()},
        checks_run,
        baseline_failures,
    )
    result = ScreenResult(
        target=company,
        domain=domain,
        jurisdiction=jurisdiction_pack.name,
        company_id=company_id,
        risk_level=risk_level(
            findings, pipeline_review_required=bool(baseline_failures)
        ),
        findings=findings,
        coverage=coverage_rows,
        usage=ledger,
    )
    if run_tree is not None:
        run_tree.add_metadata(
            {
                "risk_level": result.risk_level,
                "candidate_count": len(candidates),
                "finding_count": len(findings),
                "verified_count": sum(
                    finding.status == "verified" for finding in findings
                ),
                "review_required_categories": sum(
                    row.status == "review_required" for row in coverage_rows
                ),
                "tavily_credits": ledger.tavily_credits,
                "tavily_credits_by_endpoint": ledger.credits_by_endpoint,
                "llm_input_tokens": ledger.llm_input_tokens,
                "llm_output_tokens": ledger.llm_output_tokens,
                "wall_seconds": round(ledger.wall_seconds, 3),
            }
        )
    _notify(progress, "complete", "IC memo complete", 100)
    return result


def _notify(
    callback: ProgressCallback | None,
    stage: str,
    message: str,
    percent: int,
) -> None:
    """Progress reporting must never become part of the decision path."""
    if callback is None:
        return
    try:
        callback(stage, message, max(0, min(percent, 100)))
    except Exception:
        pass


def _narrative(llm: LLM, finding: Finding) -> str:
    if finding.status == "unresolved":
        if finding.processing_failures:
            return (
                "Sources were retrieved, but their relationship to this claim "
                "could not be classified reliably. Human review is required."
            )
        return UNRESOLVED_NARRATIVE.format(category=finding.candidate.category)
    if finding.status == "rejected" or not finding.evidence:
        return ""
    evidence_block = "\n".join(
        f'- {e.publisher} ({e.source_tier}): "{e.quote}"' for e in finding.evidence
    )
    try:
        return llm.text(
            NARRATIVE_PROMPT.format(
                claim=finding.candidate.claim,
                status=finding.status,
                evidence=evidence_block,
            )
        )
    except Exception:
        # Narrative prose is presentation-only; the validated quotes and gate
        # result remain usable if generation fails.
        return "Narrative generation was unavailable; review the quoted evidence below."
