from copy import deepcopy

import pytest

from deallens.evalrun import (
    EntityCaseResult,
    GateCaseResult,
    GovernanceCaseResult,
    compare_reports,
    evaluation_report,
)


def sample_report() -> dict:
    return evaluation_report(
        [GateCaseResult("gate_case", "reported", "reported", 0, 0)],
        [EntityCaseResult("entity_case", [], [])],
        [
            GovernanceCaseResult(
                "governance_case",
                ("primary", False, True, True),
                ("primary", False, True, True),
            )
        ],
    )


def test_case_level_report_is_stable_and_namespaced():
    report = sample_report()

    assert report["schema_version"] == 2
    assert report["summary"]["total_cases"] == 3
    assert report["cases"]["evidence_gate"][0]["name"] == "gate_case"
    assert report["cases"]["entity_resolution"][0]["passed"] is True


def test_baseline_comparison_detects_regression_and_removed_coverage():
    baseline = sample_report()
    current = deepcopy(baseline)
    current["cases"]["evidence_gate"][0]["passed"] = False
    current["cases"]["source_governance"] = []
    current["summary"]["total_cases"] = 2

    comparison = compare_reports(current, baseline)

    assert comparison["passed"] is False
    assert comparison["regressions"] == ["evidence_gate/gate_case"]
    assert comparison["removed_cases"] == ["source_governance/governance_case"]
    assert comparison["metrics"]["total_cases_delta"] == -1


def test_legacy_summary_baseline_still_compares_safety_metrics():
    current = sample_report()
    comparison = compare_reports(current, current["summary"])

    assert comparison["available"] is True
    assert comparison["history_available"] is False
    assert comparison["passed"] is True


def test_duplicate_case_names_are_rejected():
    duplicate = GateCaseResult("same_case", "reported", "reported", 0, 0)

    with pytest.raises(ValueError, match="Duplicate eval case names"):
        evaluation_report([duplicate, duplicate], [], [])
