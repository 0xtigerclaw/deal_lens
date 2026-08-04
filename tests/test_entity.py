from deallens.config import load_jurisdiction, registry_domain
from deallens.entity import (
    COMPANIES_HOUSE_DOMAIN,
    rank_registry_results,
    resolve_entity,
)
from deallens.models import UsageLedger


class FakeTavily:
    def __init__(self, results: list[dict]):
        self.results = results
        self.calls: list[dict] = []
        self.ledger = UsageLedger()

    def search(self, **kwargs):
        self.calls.append(kwargs)
        self.ledger.add_credits("search", 1)
        return {"results": self.results}


def companies_house_result(
    name: str,
    company_id: str,
    *,
    score: float = 0.9,
    path: str = "overview",
) -> dict:
    return {
        "title": f"{name} {path} - Find and update company information - GOV.UK",
        "url": f"https://{COMPANIES_HOUSE_DOMAIN}/company/{company_id}/{path}",
        "score": score,
    }


def test_registry_domain_is_read_from_jurisdiction_configuration():
    assert registry_domain(load_jurisdiction("UK")) == COMPANIES_HOUSE_DOMAIN


def test_registry_results_are_constrained_deduplicated_and_ranked():
    results = [
        companies_house_result("GROUP MONZO LTD", "15034063", score=0.99),
        companies_house_result("MONZO BANK LIMITED", "09446231", score=0.98),
        companies_house_result(
            "MONZO BANK LIMITED", "09446231", score=0.72, path="filing-history"
        ),
        companies_house_result("MONZO CONSULTING LIMITED", "12000001", score=0.71),
        companies_house_result("UNRELATED BUSINESS LIMITED", "12000002", score=0.99),
        {
            "title": "MONZO BANK LIMITED",
            "url": "https://malicious.example/company/09446231",
            "score": 1,
        },
    ]

    candidates = rank_registry_results("Monzo", results, COMPANIES_HOUSE_DOMAIN)

    assert [candidate.company_id for candidate in candidates] == [
        "09446231",
        "12000001",
        "15034063",
    ]
    assert candidates[0].legal_name == "MONZO BANK LIMITED"
    assert candidates[0].confidence > candidates[1].confidence


def test_registry_ranker_abstains_when_name_does_not_match():
    candidates = rank_registry_results(
        "Monzo",
        [companies_house_result("UNRELATED BUSINESS LIMITED", "12000002")],
        COMPANIES_HOUSE_DOMAIN,
    )

    assert candidates == []


def test_entity_resolution_uses_only_configured_registry_and_books_usage():
    tavily = FakeTavily(
        [companies_house_result("MONZO BANK LIMITED", "09446231")]
    )

    resolution = resolve_entity(
        tavily,
        load_jurisdiction("UK"),
        "Monzo",
        "monzo.com",
    )

    assert resolution.candidates[0].company_id == "09446231"
    assert resolution.tavily_credits == 1
    assert tavily.calls == [
        {
            "query": (
                f'site:{COMPANIES_HOUSE_DOMAIN} "Monzo" company monzo.com'
            ),
            "include_domains": [COMPANIES_HOUSE_DOMAIN],
            "max_results": 8,
        }
    ]
