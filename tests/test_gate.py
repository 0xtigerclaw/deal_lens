"""Offline tests for the evidence gate — every classification row, the
failure-mode traps, severity escalation, coverage, and risk rollup."""

from deallens.config import JurisdictionPack, Policy, PolicyRule
from deallens.gate import (
    apply_severity,
    classify,
    coverage,
    quote_in_content,
    risk_level,
)
from deallens.models import Candidate, Evidence


def candidate(
    category="leadership",
    claim="The CFO departed in March 2026",
    assertions=None,
):
    return Candidate(
        category=category,
        claim=claim,
        verification_query="Acme CFO departure",
        assertions=assertions or [],
    )


def evidence(
    tier,
    publisher,
    quote="Jane Smith's appointment was terminated",
    supports=None,
    contradicts=None,
):
    return Evidence(
        url=f"https://{publisher}/x",
        publisher=publisher,
        source_tier=tier,
        quote=quote,
        supports_assertions=[0] if supports is None else supports,
        contradicts_assertions=contradicts or [],
    )


# ---- classification rows ----------------------------------------------------

def test_one_primary_source_verifies():
    f = classify(candidate(), [evidence("primary", "thegazette.co.uk")], [])
    assert f.status == "verified"


def test_two_independent_secondaries_verify():
    f = classify(
        candidate(),
        [evidence("credible_secondary", "ft.com"),
         evidence("credible_secondary", "reuters.com")],
        [],
    )
    assert f.status == "verified"


def test_two_secondaries_same_domain_only_report():
    """Syndication trap: two articles on one domain are one voice."""
    f = classify(
        candidate(),
        [evidence("credible_secondary", "ft.com"),
         evidence("credible_secondary", "ft.com", quote="second article")],
        [],
    )
    assert f.status == "reported"


def test_single_secondary_reports():
    f = classify(candidate(), [evidence("credible_secondary", "bbc.co.uk")], [])
    assert f.status == "reported"


def test_extraction_failure_is_unresolved_never_verified():
    """The trap from the spec: a candidate whose backing document cannot be
    extracted must surface as UNRESOLVED, not silently verified or dropped."""
    f = classify(candidate("regulatory"), [], ["https://fca.org.uk/blocked-doc"])
    assert f.status == "unresolved"


def test_quote_processing_failure_is_unresolved_never_clean():
    f = classify(
        candidate("cyber"),
        [],
        [],
        processing_failures=["Nebius output limit"],
    )
    assert f.status == "unresolved"


def test_other_tier_evidence_alone_is_rejected():
    """Aggregator-only trap: sources outside both tiers cannot support a
    finding, and with no extraction failures the claim is rejected."""
    f = classify(candidate(), [evidence("other", "randomblog.example")], [])
    assert f.status == "rejected"


def test_first_party_disclosure_alone_cannot_verify_itself():
    f = classify(candidate(), [evidence("first_party", "acme.com")], [])
    assert f.status == "rejected"


def test_no_evidence_no_failures_is_rejected():
    f = classify(candidate(), [], [])
    assert f.status == "rejected"


def test_primary_wins_even_with_failures_present():
    f = classify(
        candidate(),
        [evidence("primary", "find-and-update.company-information.service.gov.uk")],
        ["https://ft.com/timeout"],
    )
    assert f.status == "verified"


def test_other_tier_does_not_count_toward_verification():
    f = classify(
        candidate(),
        [evidence("credible_secondary", "ft.com"),
         evidence("other", "randomblog.example")],
        [],
    )
    assert f.status == "reported"


def test_compound_claim_is_partial_until_every_assertion_is_supported():
    c = candidate(
        claim="The CEO resigned and the chair became interim CEO",
        assertions=["The CEO resigned", "The chair became interim CEO"],
    )
    f = classify(c, [evidence("primary", "thegazette.co.uk", supports=[0])], [])
    assert f.status == "partial"


def test_compound_claim_verifies_when_each_assertion_meets_threshold():
    c = candidate(
        claim="The CEO resigned and the chair became interim CEO",
        assertions=["The CEO resigned", "The chair became interim CEO"],
    )
    f = classify(
        c,
        [
            evidence("primary", "thegazette.co.uk", supports=[0]),
            evidence("primary", "fca.org.uk", supports=[1]),
        ],
        [],
    )
    assert f.status == "verified"


def test_qualifying_contrary_evidence_cannot_verify_a_claim():
    f = classify(
        candidate(),
        [
            evidence(
                "primary", "fca.org.uk", supports=[], contradicts=[0]
            )
        ],
        [],
    )
    assert f.status == "contradicted"


def test_supporting_and_contrary_evidence_is_conflicting():
    f = classify(
        candidate(),
        [
            evidence("primary", "thegazette.co.uk", supports=[0]),
            evidence("primary", "fca.org.uk", supports=[], contradicts=[0]),
        ],
        [],
    )
    assert f.status == "conflicting"


# ---- quote validation --------------------------------------------------------

def test_quote_validates_verbatim():
    content = "Filing history.\n\nJane   Smith's appointment\nwas terminated on 14 March 2026."
    assert quote_in_content("Jane Smith's appointment was terminated", content)


def test_quote_validates_across_curly_punctuation():
    content = "Jane Smith’s appointment was terminated — effective immediately."
    assert quote_in_content("Jane Smith's appointment was terminated - effective", content)


def test_paraphrase_fails_validation():
    content = "The CFO left the company in March."
    assert not quote_in_content("The CFO resigned in March", content)


def test_empty_quote_never_validates():
    assert not quote_in_content("   ", "anything at all")


# ---- severity policy ----------------------------------------------------------

POLICY = Policy(rules={
    "leadership": PolicyRule(base="medium", escalate_when=["cfo", "founder"]),
    "cyber": PolicyRule(base="high", escalate_when=["customer data"]),
})


def test_severity_escalates_on_keyword():
    f = classify(candidate(), [evidence("primary", "thegazette.co.uk")], [])
    f = apply_severity(f, POLICY)
    assert f.severity == "high"
    assert f.policy_triggers == ["cfo"]


def test_severity_base_when_no_trigger():
    f = classify(
        candidate(claim="A regional sales manager resigned"),
        [evidence("primary", "thegazette.co.uk", quote="manager resigned")],
        [],
    )
    f = apply_severity(f, POLICY)
    assert f.severity == "medium"
    assert f.policy_triggers == []


def test_high_base_does_not_overflow():
    f = classify(
        candidate("cyber", "Ransomware exposed customer data"),
        [evidence("primary", "ico.org.uk", quote="customer data was accessed")],
        [],
    )
    f = apply_severity(f, POLICY)
    assert f.severity == "high"


def test_unresolved_and_rejected_carry_no_severity():
    unresolved = apply_severity(classify(candidate(), [], ["url"]), POLICY)
    rejected = apply_severity(classify(candidate(), [], []), POLICY)
    assert unresolved.severity is None
    assert rejected.severity is None


# ---- coverage + risk rollup ----------------------------------------------------

def test_coverage_marks_untouched_category_as_not_checked():
    f = classify(candidate(), [evidence("primary", "thegazette.co.uk")], [])
    cov = {c.category: c.status for c in coverage([f])}
    assert cov["leadership"] == "verified_finding"
    assert cov["cyber"] == "not_checked"


def test_coverage_requires_a_recorded_check_before_no_finding():
    cov = {c.category: c.status for c in coverage([], checks_run={"cyber": 1})}
    assert cov["cyber"] == "checked_no_finding"


def test_coverage_failure_cannot_be_reported_as_checked_clean():
    rows = coverage(
        [],
        checks_run={"cyber": 1},
        check_failures={"cyber": "interpretation unavailable"},
    )
    cyber = next(row for row in rows if row.category == "cyber")
    assert cyber.status == "review_required"
    assert cyber.note == "interpretation unavailable"


def test_risk_review_required_on_verified():
    f = classify(candidate(), [evidence("primary", "thegazette.co.uk")], [])
    assert risk_level([f]) == "REVIEW REQUIRED"


def test_risk_review_required_on_unresolved_alone():
    """An unresolved check alone demands human eyes."""
    f = classify(candidate("regulatory"), [], ["https://fca.org.uk/blocked"])
    assert risk_level([f]) == "REVIEW REQUIRED"


def test_risk_review_required_on_pipeline_interpretation_failure():
    rejected = classify(candidate(), [], [])
    assert risk_level([rejected], pipeline_review_required=True) == "REVIEW REQUIRED"


def test_risk_proceed_with_notes_on_reported():
    f = apply_severity(
        classify(candidate(claim="office move"), [evidence("credible_secondary", "ft.com", quote="office move")], []),
        POLICY,
    )
    assert risk_level([f]) == "PROCEED WITH NOTES"


def test_risk_no_qualifying_findings_when_only_rejected():
    assert risk_level([classify(candidate(), [], [])]) == "NO QUALIFYING FINDINGS"


# ---- jurisdiction tiering -------------------------------------------------------

PACK = JurisdictionPack(
    name="UK",
    primary=["thegazette.co.uk", "fca.org.uk"],
    credible_secondary=["ft.com"],
    exclude=["crunchbase.com"],
)


def test_tier_suffix_matching():
    assert PACK.tier_for("https://www.thegazette.co.uk/notice/123") == "primary"
    assert PACK.tier_for("https://markets.ft.com/story") == "credible_secondary"
    assert PACK.tier_for("https://someblog.example/post") == "other"


def test_tier_rejects_lookalike_domains():
    assert PACK.tier_for("https://notfca.org.uk/warning") == "other"
    assert PACK.tier_for("https://fca.org.uk.evil.example/x") == "other"


def test_excluded_domains_flagged():
    assert PACK.is_excluded("https://www.crunchbase.com/org/acme")
    assert not PACK.is_excluded("https://ft.com/content/1")


def test_publisher_identity_collapses_subdomains():
    assert PACK.publisher_for("https://markets.ft.com/story") == "ft.com"
    assert PACK.publisher_for("https://www.ft.com/story") == "ft.com"
