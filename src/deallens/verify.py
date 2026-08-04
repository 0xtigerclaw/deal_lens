"""Verification: source-governed /search per candidate.

Governance lives here, not in discovery: include/exclude domain filters come
from the jurisdiction pack, so what counts as a checkable source is customer
configuration. Two searches per candidate — a targeted query across both
trusted tiers, and a registry query against the corporate register.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from langsmith import traceable

from .config import JurisdictionPack, registry_domain
from .models import Candidate
from .tavily_client import Tavily

MAX_EXTRACT_URLS = 3
REGISTRY_CATEGORIES = {"leadership", "distress"}
NON_DOCUMENT_PATHS = re.compile(
    r"(?:^|/)(?:sitemap(?:[_-][^/]*)?\.xml|sitemap|search|tags?|authors?)(?:/|$)",
    re.IGNORECASE,
)


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


@traceable(name="deallens.verify")
def verify(
    tavily: Tavily,
    pack: JurisdictionPack,
    company: str,
    candidate: Candidate,
    company_id: str | None = None,
    baseline_results: list[dict] | None = None,
) -> tuple[list[dict], int, int]:
    """Run governed searches; return results, sources reviewed, checks run."""
    results: list[dict] = list(baseline_results or [])
    # Baseline results are reused here but were already counted when fetched.
    checks_run = 0

    targeted = tavily.search(
        query=candidate.verification_query,
        include_domains=pack.primary + pack.credible_secondary,
        exclude_domains=pack.exclude,
        max_results=8,
    )
    results.extend(targeted.get("results", []))
    checks_run += 1

    registry = registry_domain(pack)
    if registry and candidate.category in REGISTRY_CATEGORIES:
        identity = f' "{company_id}"' if company_id else ""
        registry_results = tavily.search(
            query=f'"{company}"{identity} {candidate.claim}'[:380],
            include_domains=[registry],
            max_results=5,
        )
        results.extend(registry_results.get("results", []))
        checks_run += 1

    seen: set[str] = set()
    unique = []
    for r in results:
        url = r.get("url", "")
        if (
            url
            and url not in seen
            and not pack.is_excluded(url)
            and _is_document_url(url)
            and _entity_matches(url, registry, company_id)
        ):
            seen.add(url)
            unique.append(r)

    return unique, len(unique), checks_run


def pick_extraction_urls(
    pack: JurisdictionPack,
    candidate: Candidate,
    results: list[dict],
    company_id: str | None = None,
) -> list[str]:
    """Choose <=3 URLs to extract: primary tier first, then credible secondary
    (by search score), then discovery's own sources as a last resort."""
    def score(r: dict) -> float:
        return float(r.get("score") or 0)

    primary = sorted(
        (
            r
            for r in results
            if pack.tier_for(r["url"]) == "primary"
            and _is_document_url(r["url"])
            and _entity_matches(r["url"], registry_domain(pack), company_id)
        ),
        key=score, reverse=True,
    )
    secondary = sorted(
        (
            r
            for r in results
            if pack.tier_for(r["url"]) == "credible_secondary"
            and _is_document_url(r["url"])
            and _entity_matches(r["url"], registry_domain(pack), company_id)
        ),
        key=score, reverse=True,
    )

    urls = [r["url"] for r in primary[:2]] + [r["url"] for r in secondary[:2]]

    for url in candidate.source_urls:
        if (
            url not in urls
            and pack.tier_for(url) != "other"
            and not pack.is_excluded(url)
            and _is_document_url(url)
            and _entity_matches(url, registry_domain(pack), company_id)
        ):
            urls.append(url)

    return urls[:MAX_EXTRACT_URLS]


def _entity_matches(
    url: str, registry_domain: str | None, company_id: str | None
) -> bool:
    """Reject a corporate-register URL for a different legal entity."""
    if not registry_domain or not company_id or _host(url) != registry_domain:
        return True
    normalized_id = re.sub(r"[^A-Za-z0-9]", "", company_id).upper()
    path = urlparse(url).path.upper()
    match = re.search(r"/COMPANY/([A-Z0-9]+)", path)
    return bool(match and match.group(1) == normalized_id)


def _is_document_url(url: str) -> bool:
    """Exclude search, author, tag, and sitemap index pages from evidence."""
    return not NON_DOCUMENT_PATHS.search(urlparse(url).path)
