"""Registry-constrained legal-entity resolution for the intake flow.

Tavily retrieves possible corporate-register records. DealLens then parses and
ranks those records deterministically; no language model selects an entity and
the caller must explicitly confirm a candidate before screening begins.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from langsmith import traceable
from pydantic import BaseModel, Field

from .config import JurisdictionPack, registry_domain
from .tavily_client import Tavily

COMPANIES_HOUSE_DOMAIN = "find-and-update.company-information.service.gov.uk"
COMPANY_PATH = re.compile(r"/company/([A-Za-z0-9]+)", re.IGNORECASE)
LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "llp",
    "ltd",
    "plc",
}
TITLE_MARKERS = (
    " overview - find and update company information",
    " filing history - find and update company information",
    " people - find and update company information",
    " officers - find and update company information",
    " charges - find and update company information",
    " insolvency - find and update company information",
    " - find and update company information",
)


class EntityCandidate(BaseModel):
    legal_name: str
    company_id: str
    registry_url: str
    confidence: float = Field(ge=0, le=1)
    source: str


class EntityResolution(BaseModel):
    query: str
    jurisdiction: str
    registry: str
    candidates: list[EntityCandidate]
    tavily_credits: float = 0


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _name_score(query: str, legal_name: str, search_score: float) -> float:
    query_tokens = [token for token in _tokens(query) if token not in LEGAL_SUFFIXES]
    name_tokens = [token for token in _tokens(legal_name) if token not in LEGAL_SUFFIXES]
    if not query_tokens or not name_tokens:
        return 0
    overlap = len(set(query_tokens) & set(name_tokens)) / len(set(query_tokens))
    query_text = " ".join(query_tokens)
    name_text = " ".join(name_tokens)
    similarity = SequenceMatcher(None, query_text, name_text).ratio()
    prefix_match = name_tokens[: len(query_tokens)] == query_tokens
    bounded_search_score = max(0.0, min(float(search_score or 0), 1.0))
    return round(
        min(
            1.0,
            0.52 * overlap
            + 0.28 * similarity
            + 0.12 * bounded_search_score
            + (0.08 if prefix_match else 0.0),
        ),
        3,
    )


def _legal_name(title: str) -> str:
    clean = " ".join(title.split()).strip(" -|")
    folded = clean.casefold()
    positions = [folded.find(marker) for marker in TITLE_MARKERS if marker in folded]
    if positions:
        clean = clean[: min(positions)].strip(" -|")
    clean = re.sub(r"\s*\([A-Za-z0-9]{6,12}\)\s*$", "", clean).strip()
    return clean


def rank_registry_results(
    company: str,
    results: list[dict],
    registry: str,
    *,
    limit: int = 3,
) -> list[EntityCandidate]:
    """Parse, deduplicate and locally rank registry search results."""
    by_id: dict[str, EntityCandidate] = {}
    for result in results:
        url = str(result.get("url") or "")
        host = (urlparse(url).hostname or "").casefold()
        if host != registry.casefold():
            continue
        match = COMPANY_PATH.search(url) if registry == COMPANIES_HOUSE_DOMAIN else None
        if not match:
            continue
        company_id = match.group(1).upper()
        legal_name = _legal_name(str(result.get("title") or ""))
        if not legal_name:
            continue
        confidence = _name_score(company, legal_name, float(result.get("score") or 0))
        if confidence < 0.56:
            continue
        candidate = EntityCandidate(
            legal_name=legal_name,
            company_id=company_id,
            registry_url=url,
            confidence=confidence,
            source=registry,
        )
        current = by_id.get(company_id)
        if current is None or candidate.confidence > current.confidence:
            by_id[company_id] = candidate
    return sorted(
        by_id.values(),
        key=lambda candidate: (-candidate.confidence, candidate.legal_name.casefold()),
    )[:limit]


@traceable(
    name="deallens.resolve_entity",
    run_type="chain",
    tags=["entity-resolution", "human-confirmation-required"],
)
def resolve_entity(
    tavily: Tavily,
    pack: JurisdictionPack,
    company: str,
    domain: str,
) -> EntityResolution:
    """Retrieve registry candidates; never decide which entity is correct."""
    registry = registry_domain(pack)
    if not registry:
        raise ValueError(f"{pack.name} has no configured corporate registry")
    if registry != COMPANIES_HOUSE_DOMAIN:
        return EntityResolution(
            query=company,
            jurisdiction=pack.name,
            registry=registry,
            candidates=[],
            tavily_credits=tavily.ledger.tavily_credits,
        )

    result = tavily.search(
        query=f'site:{registry} "{company}" company {domain}'[:400],
        include_domains=[registry],
        max_results=8,
        country=pack.tavily_country,
    )
    candidates = rank_registry_results(
        company,
        list(result.get("results") or []),
        registry,
    )
    return EntityResolution(
        query=company,
        jurisdiction=pack.name,
        registry=registry,
        candidates=candidates,
        tavily_credits=tavily.ledger.tavily_credits,
    )
