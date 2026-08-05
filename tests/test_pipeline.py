"""End-to-end offline contract for adaptive Tavily orchestration."""

from deallens.config import JurisdictionPack, Policy
from deallens.llm import CandidateList, QuotePick, QuoteSelection
from deallens.memo import render_memo
from deallens.models import Candidate, UsageLedger
from deallens.pipeline import run_screen


class PipelineTavily:
    def __init__(self):
        self.ledger = UsageLedger()
        self.search_calls = []
        self.extract_calls = 0

    def research(self, **_kwargs):
        self.ledger.add_credits("research", 1)
        return {
            "content": {
                "candidates": [
                    {
                        "category": "cyber",
                        "claim": "Acme disclosed that customer records were accessed",
                        "verification_query": '"Acme" customer records accessed',
                        "assertions": ["Acme customer records were accessed"],
                    }
                ]
            }
        }

    def map(self, **_kwargs):
        self.ledger.add_credits("map", 1)
        return {"results": ["https://acme.com/investors/incident"]}

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        self.ledger.add_credits("search", 2 if kwargs["search_depth"] == "advanced" else 1)
        return {"results": []}

    def extract(self, **_kwargs):
        self.extract_calls += 1
        self.ledger.add_credits("extract", 1)
        return {
            "results": [
                {
                    "url": "https://acme.com/investors/incident",
                    "raw_content": "Acme disclosed that customer records were accessed.",
                }
            ],
            "failed_results": [],
        }


class PipelineLLM:
    def __init__(self):
        self.ledger = UsageLedger()

    def structured(self, schema, _prompt):
        if schema is CandidateList:
            return CandidateList(
                candidates=[
                    Candidate(
                        category="cyber",
                        claim="Acme disclosed that customer records were accessed",
                        verification_query='"Acme" customer records accessed',
                        assertions=["Acme customer records were accessed"],
                        source_urls=["https://acme.com/investors/incident"],
                    )
                ]
            )
        return QuoteSelection(
            picks=[
                QuotePick(
                    url="https://acme.com/investors/incident",
                    quote="customer records were accessed",
                    supports_assertions=[0],
                )
            ]
        )


def test_pipeline_records_map_contribution_without_first_party_self_verification():
    tavily = PipelineTavily()
    result = run_screen(
        company="Acme",
        domain="acme.com",
        jurisdiction_pack=JurisdictionPack(
            name="UK", tavily_country="united kingdom"
        ),
        policy=Policy(),
        tavily=tavily,
        llm=PipelineLLM(),
    )

    assert result.findings[0].status == "rejected"
    assert result.findings[0].evidence[0].source_tier == "first_party"
    assert {item.method for item in result.findings[0].candidate.provenance} == {
        "research",
        "first_party_map",
    }
    assert result.retrieval_metrics.research_candidates == 1
    assert result.retrieval_metrics.map_incremental_candidates == 0
    assert result.retrieval_metrics.map_urls_reviewed == 1
    assert result.retrieval_metrics.map_status == "completed"
    assert any(call["topic"] == "finance" for call in tavily.search_calls)
    assert any(call["search_depth"] == "advanced" for call in tavily.search_calls)
    assert all(
        call.get("country") == "united kingdom"
        for call in tavily.search_calls
        if call.get("topic", "general") == "general"
    )
    memo = render_memo(result)
    assert "Tavily provenance: first party map" in memo
    assert "Candidate contribution: Research 1; baseline +0; first-party Map +0" in memo
