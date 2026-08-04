"""Discovery coverage and candidate-merging contract tests."""

from deallens.config import JurisdictionPack
from deallens.discover import (
    baseline_checks,
    discover_from_baseline,
    merge_candidates,
)
from deallens.llm import CandidateList
from deallens.models import CATEGORIES, Candidate


class SearchRecorder:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "results": [
                {
                    "url": "https://www.ft.com/acme",
                    "title": "Acme result",
                    "content": "Snippet",
                }
            ]
        }


PACK = JurisdictionPack(
    name="UK",
    primary=["fca.org.uk"],
    credible_secondary=["ft.com"],
    exclude=["crunchbase.com"],
)


def make_candidate(claim: str, category="leadership"):
    return Candidate(
        category=category,
        claim=claim,
        verification_query='"Acme" event',
        assertions=[claim],
    )


def test_baseline_runs_one_governed_search_for_every_category():
    tavily = SearchRecorder()

    results = baseline_checks(tavily, PACK, "Acme Ltd", "01234567")

    assert set(results) == set(CATEGORIES)
    assert len(tavily.calls) == len(CATEGORIES)
    assert all('"Acme Ltd"' in call["query"] for call in tavily.calls)
    assert all(call["include_domains"] == ["fca.org.uk", "ft.com"] for call in tavily.calls)
    assert all(call["exclude_domains"] == ["crunchbase.com"] for call in tavily.calls)


def test_merge_candidates_deduplicates_close_phrasings_within_category():
    research = make_candidate("The chief executive resigned on 30 January")
    baseline = make_candidate("Chief executive resigned on January 30")

    merged = merge_candidates([research], [baseline])

    assert merged == [research]


def test_merge_candidates_keeps_same_words_in_different_risk_categories():
    leadership = make_candidate("The chief executive resigned", "leadership")
    regulatory = make_candidate("The chief executive resigned", "regulatory")

    assert merge_candidates([leadership], [regulatory]) == [leadership, regulatory]


def test_candidate_assertions_cannot_drop_exact_claim_date():
    candidate = Candidate(
        category="regulatory",
        claim="The founder faced extradition as of September 2022.",
        verification_query='"Acme" founder extradition',
        assertions=[
            "The person was Acme's founder.",
            "The person faced extradition.",
        ],
    )

    assert candidate.assertions[-1] == (
        "The claimed event occurred on September 2022."
    )


def test_candidate_assertions_cannot_drop_exact_claim_quantity():
    candidate = Candidate(
        category="distress",
        claim="Acme cut 500 jobs after reporting a £5m loss.",
        verification_query='"Acme" jobs loss',
        assertions=["Acme cut jobs.", "Acme reported a loss."],
    )

    assert "The claim includes the reported quantity 500 jobs." in candidate.assertions
    assert "The claim includes the reported quantity £5m." in candidate.assertions


def test_baseline_interpretation_is_split_into_one_call_per_category():
    class CategoryLLM:
        def __init__(self):
            self.prompts = []

        def structured(self, _schema, prompt):
            self.prompts.append(prompt)
            category = next(c for c in CATEGORIES if f"governed {c} search" in prompt)
            return CandidateList(
                candidates=[make_candidate(f"{category} event", category)]
            )

    llm = CategoryLLM()
    baseline = {
        category: [
            {
                "url": f"https://www.ft.com/{category}",
                "title": f"{category} result",
                "content": "A concrete dated event",
            }
        ]
        for category in CATEGORIES
    }

    candidates, failures = discover_from_baseline(llm, "Acme Ltd", baseline)

    assert len(llm.prompts) == 4
    assert {candidate.category for candidate in candidates} == set(CATEGORIES)
    assert failures == {}


def test_baseline_interpretation_failure_is_local_and_reported():
    class OneFailureLLM:
        def structured(self, _schema, prompt):
            category = next(c for c in CATEGORIES if f"governed {c} search" in prompt)
            if category == "cyber":
                raise RuntimeError("provider length limit")
            return CandidateList(candidates=[])

    baseline = {
        category: [
            {
                "url": f"https://www.ft.com/{category}",
                "title": "Result",
                "content": "Snippet",
            }
        ]
        for category in CATEGORIES
    }

    candidates, failures = discover_from_baseline(
        OneFailureLLM(), "Acme Ltd", baseline
    )

    assert candidates == []
    assert set(failures) == {"cyber"}
    assert "human review" in failures["cyber"]
