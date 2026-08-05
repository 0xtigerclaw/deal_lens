"""Claim-level Tavily provenance and first-party capture contracts."""

from deallens.capture import capture
from deallens.config import JurisdictionPack
from deallens.llm import QuotePick, QuoteSelection
from deallens.models import Candidate


class ExtractTavily:
    def extract(self, **_kwargs):
        return {
            "results": [
                {
                    "url": "https://acme.com/investors/incident",
                    "raw_content": "Acme disclosed that customer records were accessed.",
                }
            ],
            "failed_results": [],
        }


class QuoteLLM:
    def structured(self, _schema, _prompt):
        return QuoteSelection(
            picks=[
                QuotePick(
                    url="https://acme.com/investors/incident",
                    quote="customer records were accessed",
                    supports_assertions=[0],
                )
            ]
        )


def test_first_party_capture_is_labelled_and_carries_tavily_provenance():
    pack = JurisdictionPack(name="UK", credible_secondary=["ft.com"])
    candidate = Candidate(
        category="cyber",
        claim="Customer records were accessed",
        verification_query='"Acme" customer records accessed',
        source_urls=["https://acme.com/investors/incident"],
    )

    evidence, failures, processing_failures = capture(
        ExtractTavily(),
        QuoteLLM(),
        pack,
        "Acme",
        candidate,
        ["https://acme.com/investors/incident"],
        [],
        target_domain="acme.com",
    )

    assert failures == []
    assert processing_failures == []
    assert evidence[0].source_tier == "first_party"
    assert [item.endpoint for item in evidence[0].provenance] == ["map", "extract"]
    assert evidence[0].provenance[0].method == "first_party_map"
