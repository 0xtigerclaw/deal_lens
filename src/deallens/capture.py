"""Evidence capture: /extract the chosen sources, then hold every quote to the
verbatim standard.

The LLM selects quotes (generative); quote_in_content validates them against
the extracted text (deterministic). A paraphrase is discarded, and a source
with no validated quote contributes nothing. Extraction failures are recorded
and flow to the gate, where they can make a finding UNRESOLVED — they are
never silently dropped.
"""

from __future__ import annotations

from langsmith import traceable

from .config import JurisdictionPack
from .gate import quote_in_content
from .llm import LLM, QuoteSelection
from .models import Candidate, Evidence
from .tavily_client import Tavily

CONTENT_CHARS_PER_SOURCE = 8000

QUOTE_PROMPT = """Candidate claim: {claim}
Company: {company}

The claim contains these atomic assertions, indexed from zero:
{assertions}

Below are extracted source contents. For each URL, copy ONE short passage
(under 60 words), copied exactly character for character. Return the zero-based
indexes of assertions that the passage FULLY supports and those it directly
contradicts. Partial support does not count: omit an index unless every material
part of that assertion is stated by the passage. If the passage is irrelevant,
return null and empty index lists. Never alter or paraphrase a passage.

"Directly contradicts" is deliberately narrow: the passage must explicitly
deny the assertion or give a mutually exclusive value for the same named
entity, role, action, and event. A different nearby filing, role, appointment,
or date is not a contradiction. When in doubt, return no relationship.

{sources}"""


@traceable(name="deallens.capture")
def capture(
    tavily: Tavily,
    llm: LLM,
    pack: JurisdictionPack,
    company: str,
    candidate: Candidate,
    urls: list[str],
    search_results: list[dict],
) -> tuple[list[Evidence], list[str], list[str]]:
    """Return validated evidence, failed URLs, and processing failures."""
    if not urls:
        return [], [], []

    extraction_query = " ".join(
        [company, candidate.claim, *candidate.assertions]
    )
    response = tavily.extract(
        urls=urls,
        query=extraction_query,
        chunks_per_source=3,
    )
    extracted = {
        r["url"]: r.get("raw_content") or ""
        for r in response.get("results", [])
        if r.get("raw_content")
    }
    failures = [f.get("url", "?") for f in response.get("failed_results", [])]
    failures += [u for u in urls if u not in extracted and u not in failures]

    if not extracted:
        return [], failures, []

    sources_block = "\n\n".join(
        f"URL: {url}\nCONTENT:\n{content[:CONTENT_CHARS_PER_SOURCE]}"
        for url, content in extracted.items()
    )
    try:
        selection = llm.structured(
            QuoteSelection,
            QUOTE_PROMPT.format(
                claim=candidate.claim,
                company=company,
                assertions="\n".join(
                    f"[{index}] {assertion}"
                    for index, assertion in enumerate(candidate.assertions)
                ),
                sources=sources_block,
            ),
        )
    except Exception as exc:
        # Extraction succeeded, but no quote relationship can be trusted. This
        # candidate becomes unresolved instead of terminating or disappearing.
        return [], failures, [
            "Nebius could not classify the extracted passages "
            f"({type(exc).__name__}); human review is required."
        ]

    titles = {r.get("url"): r.get("title", "") for r in search_results}
    dates = {r.get("url"): r.get("published_date") for r in search_results}

    evidence: list[Evidence] = []
    for pick in selection.picks:
        content = extracted.get(pick.url)
        if not pick.quote or content is None:
            continue
        if not quote_in_content(pick.quote, content):
            continue  # paraphrase or fabrication — discarded, not repaired
        valid_indexes = set(range(len(candidate.assertions)))
        supports = sorted(set(pick.supports_assertions) & valid_indexes)
        contradicts = sorted(set(pick.contradicts_assertions) & valid_indexes)
        # An assertion cannot be both supported and contradicted by one passage.
        overlap = set(supports) & set(contradicts)
        supports = [index for index in supports if index not in overlap]
        contradicts = [index for index in contradicts if index not in overlap]
        if not supports and not contradicts:
            continue
        evidence.append(
            Evidence(
                url=pick.url,
                title=titles.get(pick.url, ""),
                publisher=pack.publisher_for(pick.url),
                published_date=dates.get(pick.url),
                source_tier=pack.tier_for(pick.url),
                quote=pick.quote,
                supports_assertions=supports,
                contradicts_assertions=contradicts,
            )
        )
    return evidence, failures, []
