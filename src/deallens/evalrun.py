"""Reproducible offline evals for DealLens's highest-risk boundaries.

The suites measure evidence gating, legal-entity resolution and source
governance. They use labelled fixtures and make no provider calls, so the same
command can gate every commit in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from .config import JurisdictionPack, registry_domain
from .entity import rank_registry_results
from .gate import classify, quote_in_content
from .models import Candidate, Evidence
from .verify import _entity_matches, _is_document_url


@dataclass
class GateCaseResult:
    name: str
    expected: str
    actual: str
    expected_discards: int
    actual_discards: int

    @property
    def passed(self) -> bool:
        return (
            self.expected == self.actual
            and self.expected_discards == self.actual_discards
        )


@dataclass
class EntityCaseResult:
    name: str
    expected_ids: list[str]
    actual_ids: list[str]

    @property
    def passed(self) -> bool:
        return self.expected_ids == self.actual_ids


@dataclass
class GovernanceCaseResult:
    name: str
    expected: tuple[str, bool, bool, bool]
    actual: tuple[str, bool, bool, bool]

    @property
    def passed(self) -> bool:
        return self.expected == self.actual


def run_gate_eval(
    fixture_path: Path, pack: JurisdictionPack
) -> list[GateCaseResult]:
    cases = json.loads(fixture_path.read_text())["cases"]
    results: list[GateCaseResult] = []
    for case in cases:
        candidate = Candidate(**case["candidate"])
        evidence: list[Evidence] = []
        discards = 0
        for source in case["sources"]:
            if quote_in_content(source["quote"], source["content"]):
                evidence.append(
                    Evidence(
                        url=source["url"],
                        publisher=pack.publisher_for(source["url"]),
                        source_tier=pack.tier_for(source["url"]),
                        quote=source["quote"],
                        supports_assertions=source.get("supports_assertions", [0]),
                        contradicts_assertions=source.get(
                            "contradicts_assertions", []
                        ),
                    )
                )
            else:
                discards += 1
        finding = classify(candidate, evidence, case["extraction_failures"])
        results.append(
            GateCaseResult(
                name=case["name"],
                expected=case["expected_status"],
                actual=finding.status,
                expected_discards=case["expected_discards"],
                actual_discards=discards,
            )
        )
    return results


def run_entity_eval(fixture_path: Path, pack: JurisdictionPack) -> list[EntityCaseResult]:
    cases = json.loads(fixture_path.read_text())["cases"]
    registry = registry_domain(pack)
    if not registry:
        raise ValueError("The eval jurisdiction has no configured registry")
    return [
        EntityCaseResult(
            name=case["name"],
            expected_ids=case["expected_ids"],
            actual_ids=[
                candidate.company_id
                for candidate in rank_registry_results(
                    case["query"], case["results"], registry
                )
            ],
        )
        for case in cases
    ]


def run_governance_eval(
    fixture_path: Path, pack: JurisdictionPack
) -> list[GovernanceCaseResult]:
    cases = json.loads(fixture_path.read_text())["cases"]
    registry = registry_domain(pack)
    results: list[GovernanceCaseResult] = []
    for case in cases:
        url = case["url"]
        expected = tuple(case["expected"])
        actual = (
            pack.tier_for(url),
            pack.is_excluded(url),
            _is_document_url(url),
            _entity_matches(url, registry, case.get("company_id")),
        )
        results.append(
            GovernanceCaseResult(
                name=case["name"],
                expected=expected,  # type: ignore[arg-type]
                actual=actual,
            )
        )
    return results


def evaluation_summary(
    gate: list[GateCaseResult],
    entity: list[EntityCaseResult],
    governance: list[GovernanceCaseResult],
) -> dict:
    non_verified = [result for result in gate if result.expected != "verified"]
    false_verifies = sum(
        result.actual == "verified" for result in non_verified
    )
    abstentions = [result for result in entity if not result.expected_ids]
    correct_abstentions = sum(not result.actual_ids for result in abstentions)
    return {
        "total_cases": len(gate) + len(entity) + len(governance),
        "all_passed": all(
            result.passed for result in [*gate, *entity, *governance]
        ),
        "evidence_gate": {
            "passed": sum(result.passed for result in gate),
            "total": len(gate),
            "false_verifies": false_verifies,
            "non_verified_cases": len(non_verified),
        },
        "entity_resolution": {
            "passed": sum(result.passed for result in entity),
            "total": len(entity),
            "correct_abstentions": correct_abstentions,
            "abstention_cases": len(abstentions),
        },
        "source_governance": {
            "passed": sum(result.passed for result in governance),
            "total": len(governance),
        },
    }


def evaluation_report(
    gate: list[GateCaseResult],
    entity: list[EntityCaseResult],
    governance: list[GovernanceCaseResult],
) -> dict[str, Any]:
    """Return a stable, case-level report suitable for a reviewed baseline."""
    names_by_suite = {
        "evidence_gate": [result.name for result in gate],
        "entity_resolution": [result.name for result in entity],
        "source_governance": [result.name for result in governance],
    }
    for suite, names in names_by_suite.items():
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"Duplicate eval case names in {suite}: {', '.join(duplicates)}"
            )
    return {
        "schema_version": 2,
        "summary": evaluation_summary(gate, entity, governance),
        "cases": {
            "evidence_gate": [
                {
                    "name": result.name,
                    "passed": result.passed,
                    "expected": {
                        "status": result.expected,
                        "discards": result.expected_discards,
                    },
                    "actual": {
                        "status": result.actual,
                        "discards": result.actual_discards,
                    },
                }
                for result in gate
            ],
            "entity_resolution": [
                {
                    "name": result.name,
                    "passed": result.passed,
                    "expected": result.expected_ids,
                    "actual": result.actual_ids,
                }
                for result in entity
            ],
            "source_governance": [
                {
                    "name": result.name,
                    "passed": result.passed,
                    "expected": list(result.expected),
                    "actual": list(result.actual),
                }
                for result in governance
            ],
        },
    }


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    """Accept both the legacy summary-only file and the v2 report schema."""
    summary = report.get("summary", report)
    return summary if isinstance(summary, dict) else {}


def _case_map(report: dict[str, Any]) -> dict[str, bool]:
    mapped: dict[str, bool] = {}
    suites = report.get("cases")
    if not isinstance(suites, dict):
        return mapped
    for suite, cases in suites.items():
        if not isinstance(cases, list):
            continue
        for case in cases:
            if isinstance(case, dict) and isinstance(case.get("name"), str):
                mapped[f"{suite}/{case['name']}"] = bool(case.get("passed"))
    return mapped


def compare_reports(
    current: dict[str, Any], baseline: dict[str, Any] | None
) -> dict[str, Any]:
    """Detect behavioral regressions, deleted coverage, fixes, and new cases."""
    if baseline is None:
        return {
            "available": False,
            "history_available": False,
            "passed": True,
            "regressions": [],
            "fixed": [],
            "new_cases": [],
            "removed_cases": [],
            "metrics": {},
        }

    current_summary = _summary(current)
    baseline_summary = _summary(baseline)
    current_cases = _case_map(current)
    baseline_cases = _case_map(baseline)
    history_available = bool(baseline_cases)

    regressions = sorted(
        case_id
        for case_id, passed in current_cases.items()
        if baseline_cases.get(case_id) is True and not passed
    )
    fixed = sorted(
        case_id
        for case_id, passed in current_cases.items()
        if baseline_cases.get(case_id) is False and passed
    )
    new_cases = sorted(set(current_cases) - set(baseline_cases)) if history_available else []
    removed_cases = (
        sorted(set(baseline_cases) - set(current_cases)) if history_available else []
    )

    current_gate = current_summary.get("evidence_gate", {})
    baseline_gate = baseline_summary.get("evidence_gate", {})
    current_false_verifies = int(current_gate.get("false_verifies", 0))
    baseline_false_verifies = int(baseline_gate.get("false_verifies", 0))

    current_entity = current_summary.get("entity_resolution", {})
    baseline_entity = baseline_summary.get("entity_resolution", {})
    current_abstention_total = int(current_entity.get("abstention_cases", 0))
    baseline_abstention_total = int(baseline_entity.get("abstention_cases", 0))
    current_abstention_rate = (
        int(current_entity.get("correct_abstentions", 0)) / current_abstention_total
        if current_abstention_total
        else 1.0
    )
    baseline_abstention_rate = (
        int(baseline_entity.get("correct_abstentions", 0)) / baseline_abstention_total
        if baseline_abstention_total
        else 1.0
    )

    metrics = {
        "total_cases_delta": int(current_summary.get("total_cases", 0))
        - int(baseline_summary.get("total_cases", 0)),
        "false_verifies_delta": current_false_verifies - baseline_false_verifies,
        "abstention_accuracy_delta": round(
            current_abstention_rate - baseline_abstention_rate, 6
        ),
    }
    passed = (
        not regressions
        and not removed_cases
        and current_false_verifies <= baseline_false_verifies
        and current_abstention_rate >= baseline_abstention_rate
    )
    return {
        "available": True,
        "history_available": history_available,
        "passed": passed,
        "regressions": regressions,
        "fixed": fixed,
        "new_cases": new_cases,
        "removed_cases": removed_cases,
        "metrics": metrics,
    }


def _table(title: str, rows: list[tuple[str, str, str]]) -> Table:
    table = Table(title=title)
    table.add_column("Case")
    table.add_column("Expected")
    table.add_column("Actual")
    table.add_column("Pass")
    for name, expected, actual in rows:
        table.add_row(name, expected, actual, "✓" if expected == actual else "✗")
    return table


def print_report(
    gate: list[GateCaseResult],
    entity: list[EntityCaseResult],
    governance: list[GovernanceCaseResult],
) -> bool:
    console = Console()
    console.print(
        _table(
            "Evidence gate + verbatim quote validation",
            [
                (
                    result.name,
                    f"{result.expected} · discard {result.expected_discards}",
                    f"{result.actual} · discard {result.actual_discards}",
                )
                for result in gate
            ],
        )
    )
    console.print(
        _table(
            "Legal-entity ranking",
            [
                (result.name, str(result.expected_ids), str(result.actual_ids))
                for result in entity
            ],
        )
    )
    console.print(
        _table(
            "Source-governance contract",
            [
                (result.name, str(result.expected), str(result.actual))
                for result in governance
            ],
        )
    )
    summary = evaluation_summary(gate, entity, governance)
    passed = (
        summary["evidence_gate"]["passed"]
        + summary["entity_resolution"]["passed"]
        + summary["source_governance"]["passed"]
    )
    console.print(f"Passed: {passed}/{summary['total_cases']} labelled cases")
    console.print(
        "False-verify rate: "
        f"{summary['evidence_gate']['false_verifies']}/"
        f"{summary['evidence_gate']['non_verified_cases']}"
    )
    console.print(
        "Entity abstention accuracy: "
        f"{summary['entity_resolution']['correct_abstentions']}/"
        f"{summary['entity_resolution']['abstention_cases']}"
    )
    return bool(summary["all_passed"])


def print_comparison(comparison: dict[str, Any]) -> bool:
    """Print the feedback-loop delta and return whether the baseline held."""
    console = Console()
    if not comparison["available"]:
        console.print("[yellow]Baseline comparison: unavailable[/yellow]")
        return True

    metrics = comparison["metrics"]
    table = Table(title="Evaluation feedback loop")
    table.add_column("Signal")
    table.add_column("Delta")
    table.add_column("Status")
    rows = [
        (
            "Labelled coverage",
            f"{metrics['total_cases_delta']:+d} cases",
            "✓" if not comparison["removed_cases"] else "✗",
        ),
        (
            "Behavior regressions",
            str(len(comparison["regressions"])),
            "✓" if not comparison["regressions"] else "✗",
        ),
        (
            "False verifies",
            f"{metrics['false_verifies_delta']:+d}",
            "✓" if metrics["false_verifies_delta"] <= 0 else "✗",
        ),
        (
            "Entity abstention accuracy",
            f"{metrics['abstention_accuracy_delta']:+.1%}",
            "✓" if metrics["abstention_accuracy_delta"] >= 0 else "✗",
        ),
        ("Fixed cases", str(len(comparison["fixed"])), "·"),
        ("New labelled cases", str(len(comparison["new_cases"])), "·"),
        (
            "Removed cases",
            str(len(comparison["removed_cases"])),
            "✓" if not comparison["removed_cases"] else "✗",
        ),
    ]
    for row in rows:
        table.add_row(*row)
    console.print(table)

    for label, key in (
        ("Regressions", "regressions"),
        ("Removed coverage", "removed_cases"),
    ):
        if comparison[key]:
            console.print(f"[red]{label}:[/red] " + ", ".join(comparison[key]))
    if not comparison["history_available"]:
        console.print(
            "[dim]Promote once to enable case-by-case regression history.[/dim]"
        )
    return bool(comparison["passed"])
