"""Discovery: /research proposes candidate red flags. Recall-first, zero trust.

The research model is told to return candidates, not conclusions, and its
output is normalized into typed Candidate objects. Nothing here counts as
evidence — every candidate must survive verify + capture + gate.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from langsmith import traceable

from .llm import LLM, CandidateList
from .config import JurisdictionPack
from .models import CATEGORIES, Candidate, Category, RetrievalProvenance
from .tavily_client import Tavily

MAX_CANDIDATES = 10
MAX_BASELINE_CANDIDATES = 6
MAX_BASELINE_CANDIDATES_PER_CATEGORY = 2
MAX_FIRST_PARTY_CANDIDATES = 3
MAX_FIRST_PARTY_URLS = 12

BASELINE_QUERY_TERMS: dict[Category, str] = {
    "leadership": "CEO CFO founder director resigned appointed ownership acquisition",
    "regulatory": "regulator investigation enforcement lawsuit court fine penalty",
    "cyber": "cybersecurity ransomware data breach hacked incident regulator",
    "distress": "insolvency administration layoffs closure overdue accounts covenant distress",
}

BASELINE_SEARCH_POLICY: dict[Category, dict[str, str]] = {
    "leadership": {"topic": "news", "time_range": "year"},
    "regulatory": {"topic": "general"},
    "cyber": {"topic": "news", "time_range": "year"},
    "distress": {"topic": "finance"},
}
BASELINE_CHECK_COUNTS: dict[Category, int] = {
    "leadership": 1,
    "regulatory": 1,
    "cyber": 1,
    "distress": 2,
}

RESEARCH_PROMPT = """Conduct a red-flag screen of {company} ({domain}), a company in {jurisdiction}.
Legal entity identifier: {company_id}.

Look for concrete, dateable events in these four categories:
- leadership: director, founder, CEO, CFO, or ownership changes
- regulatory: regulator investigations, enforcement actions, material litigation
- cyber: cybersecurity incidents, customer-data breaches
- distress: insolvency proceedings, layoffs, facility closures, overdue filings, covenant or funding problems

Return candidate findings, not conclusions. For every candidate include:
the category, a one-sentence specific claim, the approximate date if known,
source URLs where you saw it, and a short verification search query containing
the company name in quotes. Also split the claim into one to three atomic
assertions. Each assertion must contain exactly one independently verifiable
fact; do not hide multiple facts behind "and" in one assertion.
Every exact date, amount, percentage, or other quantity in the claim must also
appear verbatim in at least one assertion. Never make the assertion set weaker
than the displayed claim.

Do not interpret a lack of findings as proof that no risk exists. Do not pad:
if a category has nothing concrete, return nothing for it. At most {max_candidates} candidates."""

OUTPUT_SCHEMA = {
    "properties": {
        "candidates": {
            "type": "array",
            "description": "Concrete red-flag hypotheses that require verification.",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["leadership", "regulatory", "cyber", "distress"],
                        "description": "Risk category for the candidate event.",
                    },
                    "claim": {
                        "type": "string",
                        "description": "One specific, dateable claim to verify.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Approximate event date; omit when unknown.",
                    },
                    "source_urls": {
                        "type": "array",
                        "description": "Source URLs found during broad discovery.",
                        "items": {"type": "string"},
                    },
                    "verification_query": {
                        "type": "string",
                        "description": "Targeted query containing the company name.",
                    },
                    "assertions": {
                        "type": "array",
                        "description": "One to three atomic facts comprising the claim.",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "category",
                    "claim",
                    "verification_query",
                    "assertions",
                ],
            },
        }
    },
    "required": ["candidates"],
}

NORMALIZE_PROMPT = """Convert this research output into candidate red-flag findings for {company}.
Only include events actually mentioned in the text; never invent claims or URLs.
Split every compound claim into one to three atomic assertions.
Preserve every exact date, amount, percentage, and quantity from the claim in
at least one assertion.

Research output:
{payload}"""

BASELINE_DISCOVERY_PROMPT = """Review these governed {category} search results for {company}.
Propose only concrete, dateable red-flag candidates explicitly stated in a title
or snippet. Treat snippets as hypotheses, never conclusions. For each candidate,
include its category, claim, source URL, a targeted verification query containing
the company name in quotes, and one to three atomic assertions. Do not infer a
red flag from ordinary corporate activity. Return at most {limit} candidates.
Every exact date, amount, percentage, or other quantity in a claim must appear
verbatim in at least one of its assertions.

Results:
{payload}"""

FIRST_PARTY_MAP_INSTRUCTIONS = (
    "Find investor relations, regulatory notices, security or data incident "
    "disclosures, leadership announcements, filings, restructuring, layoffs, "
    "closures, and financial distress pages. Exclude product, support, careers, "
    "marketing, privacy policy, and generic legal pages."
)

FIRST_PARTY_DISCOVERY_PROMPT = """Review these pages published on {company}'s own website.
Propose only concrete, dateable red-flag candidates explicitly stated in the
content. First-party statements are hypotheses requiring independent
verification. Use only URLs present below, preserve exact dates and quantities,
and return at most {limit} candidates across leadership, regulatory, cyber, and
distress. Split each claim into one to three atomic assertions.

Pages:
{payload}"""


@traceable(name="deallens.discover")
def discover(
    tavily: Tavily,
    llm: LLM,
    company: str,
    domain: str,
    jurisdiction: str,
    company_id: str | None = None,
) -> list[Candidate]:
    response = tavily.research(
        input=RESEARCH_PROMPT.format(
            company=company,
            domain=domain,
            jurisdiction=jurisdiction,
            company_id=company_id or "not supplied",
            max_candidates=MAX_CANDIDATES,
        ),
        output_schema=OUTPUT_SCHEMA,
    )
    candidates = _parse(response, company, llm)[:MAX_CANDIDATES]
    for candidate in candidates:
        candidate.provenance.append(
            RetrievalProvenance(
                method="research",
                endpoint="research",
                query=f"Acquisition red-flag screen for {company}",
            )
        )
    return candidates


def _parse(response: dict, company: str, llm: LLM) -> list[Candidate]:
    """Prefer the structured payload; fall back to one local normalization call."""
    payload = (
        response.get("content")
        or response.get("output")
        or response.get("results")
        or response.get("answer")
    )

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            pass

    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        out = []
        for raw in payload["candidates"]:
            try:
                out.append(Candidate(**raw))
            except Exception:
                continue  # one malformed candidate should not sink the screen
        return out

    normalized = llm.structured(
        CandidateList,
        NORMALIZE_PROMPT.format(company=company, payload=str(payload)[:20000]),
    )
    return normalized.candidates


@traceable(name="deallens.baseline_checks")
def baseline_checks(
    tavily: Tavily,
    pack: JurisdictionPack,
    company: str,
    company_id: str | None = None,
) -> dict[Category, list[dict]]:
    """Run one governed check for every risk category, regardless of discovery."""
    output: dict[Category, list[dict]] = {}
    for category in CATEGORIES:
        policies = [BASELINE_SEARCH_POLICY[category]]
        if category == "distress":
            policies.append({"topic": "general"})
        query = f'"{company}" {BASELINE_QUERY_TERMS[category]}'
        output[category] = []
        for policy in policies:
            response = tavily.search(
                # News rarely contains a registration number; legal-entity IDs are
                # enforced later on registry URLs rather than reducing web recall.
                query=query,
                include_domains=pack.primary + pack.credible_secondary,
                exclude_domains=pack.exclude,
                max_results=8,
                search_depth="basic",
                topic=policy["topic"],
                country=(
                    pack.tavily_country
                    if policy["topic"] == "general"
                    else None
                ),
                time_range=policy.get("time_range"),
            )
            for result in response.get("results", []):
                if not result.get("url") or pack.is_excluded(result["url"]):
                    continue
                result = dict(result)
                result["_deallens_query"] = query
                result["_deallens_topic"] = policy["topic"]
                result["_deallens_country"] = (
                    pack.tavily_country
                    if policy["topic"] == "general"
                    else None
                )
                result["_deallens_search_depth"] = "basic"
                output[category].append(result)
    return output


@traceable(name="deallens.discover_from_baseline")
def discover_from_baseline(
    llm: LLM,
    company: str,
    baseline: dict[Category, list[dict]],
) -> tuple[list[Candidate], dict[Category, str]]:
    candidates: list[Candidate] = []
    failures: dict[Category, str] = {}
    for category, results in baseline.items():
        rows = []
        for result in results:
            rows.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("content", "")[:400],
                    "published_date": result.get("published_date"),
                }
            )
        if not rows:
            continue
        try:
            parsed = llm.structured(
                CandidateList,
                BASELINE_DISCOVERY_PROMPT.format(
                    company=company,
                    category=category,
                    limit=MAX_BASELINE_CANDIDATES_PER_CATEGORY,
                    payload=json.dumps(rows)[:8000],
                ),
            )
        except Exception as exc:
            # Baseline search is a recall supplement to Tavily Research. A
            # noisy category must not erase the other completed checks, but it
            # also must never be reported as checked-clean.
            failures[category] = (
                "Nebius could not interpret the retrieved baseline results "
                f"({type(exc).__name__}); human review is required."
            )
            continue
        category_candidates = [
            candidate
            for candidate in parsed.candidates
            if candidate.category == category
        ]
        candidates.extend(
            category_candidates[:MAX_BASELINE_CANDIDATES_PER_CATEGORY]
        )
        for candidate in category_candidates[:MAX_BASELINE_CANDIDATES_PER_CATEGORY]:
            seen_searches: set[tuple[str, str]] = set()
            for result in results:
                query = str(
                    result.get("_deallens_query") or f'"{company}" {category}'
                )
                topic = str(result.get("_deallens_topic") or "general")
                if (query, topic) in seen_searches:
                    continue
                seen_searches.add((query, topic))
                candidate.provenance.append(
                    RetrievalProvenance(
                        method="baseline_search",
                        endpoint="search",
                        query=query,
                        topic=topic,
                        country=result.get("_deallens_country"),
                        search_depth="basic",
                    )
                )
    return candidates[:MAX_BASELINE_CANDIDATES], failures


@traceable(name="deallens.first_party_discovery")
def discover_first_party(
    tavily: Tavily,
    llm: LLM,
    company: str,
    domain: str,
) -> tuple[list[Candidate], set[str], str | None]:
    """Map and selectively extract the target site for disclosed risk signals.

    This channel is recall-only. Its sources receive the non-qualifying
    ``first_party`` tier during evidence capture and cannot verify themselves.
    """
    root_url = f"https://{domain}"
    try:
        mapped = tavily.map(
            url=root_url,
            instructions=FIRST_PARTY_MAP_INSTRUCTIONS,
            limit=MAX_FIRST_PARTY_URLS,
        )
        host = (urlparse(root_url).hostname or "").removeprefix("www.")
        urls = [
            str(url)
            for url in mapped.get("results", [])
            if (urlparse(str(url)).hostname or "").removeprefix("www.") == host
        ][:MAX_FIRST_PARTY_URLS]
        if not urls:
            return [], set(), None
        extraction_query = (
            f"{company} leadership regulatory security incident breach filings "
            "restructuring layoffs closure financial distress"
        )
        extracted = tavily.extract(
            urls=urls,
            query=extraction_query,
            chunks_per_source=3,
        )
        pages = [
            {
                "url": row.get("url"),
                "content": (row.get("raw_content") or "")[:5000],
            }
            for row in extracted.get("results", [])
            if row.get("url") and row.get("raw_content")
        ]
        if not pages:
            return [], set(urls), None
        parsed = llm.structured(
            CandidateList,
            FIRST_PARTY_DISCOVERY_PROMPT.format(
                company=company,
                limit=MAX_FIRST_PARTY_CANDIDATES,
                payload=json.dumps(pages)[:16000],
            ),
        )
        allowed_urls = {str(page["url"]) for page in pages}
        candidates = parsed.candidates[:MAX_FIRST_PARTY_CANDIDATES]
        for candidate in candidates:
            candidate.source_urls = [
                url for url in candidate.source_urls if url in allowed_urls
            ]
            candidate.provenance.append(
                RetrievalProvenance(
                    method="first_party_map",
                    endpoint="map",
                    query=FIRST_PARTY_MAP_INSTRUCTIONS,
                    source_url=root_url,
                )
            )
        return candidates, allowed_urls, None
    except Exception as exc:
        return [], set(), f"First-party disclosure mapping failed ({type(exc).__name__})."


def merge_candidates(*candidate_lists: list[Candidate]) -> list[Candidate]:
    """Deduplicate close phrasings without asking another model to adjudicate."""
    merged: list[Candidate] = []
    for candidate in (item for group in candidate_lists for item in group):
        tokens = _claim_tokens(candidate.claim)
        duplicate = next(
            (
                prior
                for prior in merged
                if candidate.category == prior.category
                and _jaccard(tokens, _claim_tokens(prior.claim)) >= 0.72
            ),
            None,
        )
        if duplicate is None:
            merged.append(candidate)
        else:
            known = {item.model_dump_json() for item in duplicate.provenance}
            duplicate.provenance.extend(
                item
                for item in candidate.provenance
                if item.model_dump_json() not in known
            )
            duplicate.source_urls = list(
                dict.fromkeys([*duplicate.source_urls, *candidate.source_urls])
            )
    return merged[:MAX_CANDIDATES]


def retrieval_ablation(
    research: list[Candidate],
    baseline: list[Candidate],
    first_party: list[Candidate],
) -> tuple[list[Candidate], dict[str, int]]:
    """Measure the incremental candidate contribution of each retrieval stage."""
    research_only = merge_candidates(research)
    with_baseline = merge_candidates(research_only, baseline)
    with_map = merge_candidates(with_baseline, first_party)
    return with_map, {
        "research_candidates": len(research_only),
        "baseline_incremental_candidates": max(
            0, len(with_baseline) - len(research_only)
        ),
        "map_incremental_candidates": max(0, len(with_map) - len(with_baseline)),
    }


def _claim_tokens(claim: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", claim.lower()) if len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 1.0
