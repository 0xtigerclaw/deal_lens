"""Reproducible offline evals for DealLens's highest-risk boundaries.

The suites measure evidence gating, legal-entity resolution and source
governance. They use labelled fixtures and make no provider calls, so the same
command can gate every commit in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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
    console.print(f"Total: {summary['total_cases']}/{summary['total_cases']} cases evaluated")
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
