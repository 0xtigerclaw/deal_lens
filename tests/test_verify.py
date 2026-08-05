"""Verification-source selection and legal-entity scoping tests."""

from deallens.config import JurisdictionPack
from deallens.models import Candidate
from deallens.verify import _entity_matches, _is_document_url, pick_extraction_urls


PACK = JurisdictionPack(
    name="UK",
    tavily_country="united kingdom",
    primary=["find-and-update.company-information.service.gov.uk"],
    credible_secondary=["ft.com"],
    exclude=["crunchbase.com"],
    registry_query='site:find-and-update.company-information.service.gov.uk "{company}"',
)


def candidate(source_urls=None):
    return Candidate(
        category="leadership",
        claim="The CEO resigned",
        verification_query='"Acme" CEO resigned',
        source_urls=source_urls or [],
    )


def test_company_house_url_must_match_requested_legal_entity():
    registry = "find-and-update.company-information.service.gov.uk"
    assert _entity_matches(
        "https://find-and-update.company-information.service.gov.uk/company/08562035/filing-history",
        registry,
        "08562035",
    )
    assert not _entity_matches(
        "https://find-and-update.company-information.service.gov.uk/company/13264637/filing-history",
        registry,
        "08562035",
    )


def test_extraction_selection_rejects_other_tier_and_wrong_entity_urls():
    urls = pick_extraction_urls(
        PACK,
        candidate(
            [
                "https://randomblog.example/rumour",
                "https://find-and-update.company-information.service.gov.uk/company/13264637/filing-history",
            ]
        ),
        [
            {
                "url": "https://find-and-update.company-information.service.gov.uk/company/13264637/filing-history",
                "score": 0.99,
            },
            {"url": "https://www.ft.com/acme", "score": 0.8},
        ],
        company_id="08562035",
    )

    assert urls == ["https://www.ft.com/acme"]


def test_non_article_indexes_are_not_evidence_documents():
    assert not _is_document_url("https://telegraph.co.uk/custom/authors/name/sitemap.xml")
    assert not _is_document_url("https://example.com/search/results")
    assert not _is_document_url("https://example.com/tag/cyber")
    assert _is_document_url("https://example.com/news/company-investigation")


def test_first_party_disclosure_can_be_extracted_but_not_external_noise():
    urls = pick_extraction_urls(
        PACK,
        candidate(
            [
                "https://acme.com/investors/security-incident",
                "https://randomblog.example/rumour",
            ]
        ),
        [],
        target_domain="acme.com",
    )

    assert urls == ["https://acme.com/investors/security-incident"]
