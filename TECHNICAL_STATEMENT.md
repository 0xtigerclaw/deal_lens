# Technical statement

## Product thesis

DealLens adapts live web research to a narrow acquisition workflow: the first
public-evidence screen of a UK private company before an analyst invests time
in full commercial, legal, financial, and cybersecurity diligence.

The expensive failure in this workflow is not missing polished prose. It is
either escalating a weak allegation as fact or presenting retrieval failure as
evidence that a category is clean. The architecture therefore optimizes for
**evidence integrity and failure visibility**, not maximum autonomy.

The central engineering rule is:

> Discovery may be probabilistic. Escalation must be deterministic.

## Why Tavily is essential rather than decorative

DealLens assigns a different retrieval responsibility to each Tavily primitive:

1. **Research for recall.** `/research` searches broadly for dateable events
   across four risk categories and returns structured candidate hypotheses.
   Its output never becomes evidence directly.
2. **Search for coverage and verification.** Four fixed baseline searches run
   even if Research returns nothing. Each candidate then receives a focused
   search constrained to primary and credible-secondary domains. Registry
   queries include the legal entity identifier when available.
3. **Extract for evidence capture.** Only a small, deterministically selected
   set of trusted URLs is extracted. The candidate claim and assertions are
   passed as the extraction query, keeping downstream model context focused.
4. **Search for entity resolution.** Before a new user spends on a screen,
   Tavily searches only the jurisdiction’s configured official registry.
   DealLens parses company numbers and ranks names locally; a human confirms.

This composition is more useful than a generic research report because it
adds coverage guarantees, source governance, legal-entity boundaries,
verbatim evidence, explicit failure states, and reproducible output.

### Why not Crawl or Map?

This is an event-screening pipeline, not a website-inventory pipeline. Search
locates claim-relevant public documents across regulators, courts, registries,
and press; Extract captures only those pages. Crawl would add own-site breadth
without strengthening the external adverse-event evidence contract, and would
make per-page failure/cost attribution less focused. It is a deliberate
non-use, not an omitted integration.

## Provider and model boundary

The assignment path uses **Nebius Token Factory** with
`moonshotai/Kimi-K3`, directly through `langchain-nebius`. There is no
Anthropic/Claude integration in runtime dependencies or code.

Kimi K3 performs bounded interpretation:

- normalize an unstructured Research response when needed;
- interpret baseline search snippets into candidate hypotheses;
- copy short passages from extracted content and map them to atomic assertions;
- label narrow, direct contradictions; and
- write short evidence-grounded narrative prose.

Kimi does **not** decide source tier, publisher independence, entity identity,
quote validity, finding status, severity, category coverage, or overall risk.
Those decisions are deterministic and unit tested. A model failure is recorded
as `REVIEW REQUIRED`; it cannot silently become “no finding.”

## Evidence and citation design

Research claims are decomposed into one to three atomic assertions. Exact
dates and quantities in the displayed claim are automatically preserved as
assertions even if model decomposition omits them. This prevents a compound
claim from becoming verified on evidence for only its easiest clause.

Kimi copies one passage per selected source. DealLens accepts the passage only
if it occurs in Tavily-extracted content after conservative punctuation and
whitespace normalization. The quote is never rewritten. A valid quote still
does not automatically verify a claim: each assertion must independently meet
one of these source thresholds:

- at least one configured primary publisher; or
- at least two independent configured credible-secondary publishers.

Source identity is derived from jurisdiction configuration, not from a model
or fixture-provided publisher label. Subdomains collapse to the configured
publisher. Excluded domains, non-document index pages, and mismatched Companies
House entity URLs are removed before extraction.

## Entity confirmation as a trust boundary

New users should not need to know a Companies House number. They also should
not unknowingly screen a similarly named entity. DealLens resolves this tension
with a confirmation checkpoint:

1. accept trading/legal name plus website;
2. search only the configured official registry using Tavily;
3. parse company identifiers from canonical registry URLs;
4. rank candidate names with deterministic token containment, string
   similarity, and Tavily result score;
5. reject low-confidence, off-domain, malformed, and duplicate records; and
6. require the analyst to confirm a record or explicitly continue without one.

No language model chooses the legal entity, and candidate display does not
automatically launch a paid screen.

## Observability and cost

LangSmith traces the complete live operation beneath `deallens.screen`.
Metadata makes a trace useful for debugging and cost review: provider/model,
pipeline version, target, jurisdiction, whether a company ID was supplied,
candidate/finding counts, final risk state, category-review count, Tavily
credits per endpoint, Nebius input/output tokens, and wall time.

Entity resolution is separately traced because it happens before human
confirmation. Tests set tracing off in `tests/conftest.py`, preventing fake
provider calls from polluting the live project.

The output artifact repeats the usage ledger. Search and Extract use Tavily’s
returned usage. Research attempts key-level before/after accounting; if that
endpoint is unavailable, `usage_complete=false` and an explanatory note are
emitted. An incomplete measured total is better than invented cost precision.

## Evaluation strategy

The offline eval targets boundaries where a false positive would undermine the
product:

- 16 evidence-gate/quote cases, including paraphrases, publisher independence,
  extraction failure, compound claims, contradiction, and conflict;
- 8 entity-ranking cases, including exact match, brand-to-legal-name match,
  deduplication, spoofed hosts, malformed records, and abstention; and
- 12 source-governance cases for suffix-safe domain tiering, exclusions,
  index-page rejection, and registry entity mismatch.

Measured result: 36/36 cases pass, with 0/11 false verifies and 4/4 correct
entity abstentions. The 73-test pytest suite covers the surrounding typed
contracts, usage, orchestration, UI API, memo, and risk roll-up.

These evals do not measure web-wide recall or memo usefulness. A production
pilot should add analyst-labelled live targets and track missed-event recall,
review acceptance, duplicate/syndicated evidence, and time saved.

## MVP scope decisions

- **Local artifacts over MongoDB.** Markdown and typed JSON are inspectable,
  portable, and sufficient for a single-analyst submission. A database becomes
  useful for multi-user retention and cross-screen retrieval, but it would not
  improve evidence correctness in this MVP.
- **One tested jurisdiction.** The UK pack is the supported path. The NL file
  is labelled preview rather than overstated.
- **Background worker, not distributed queue.** The FastAPI executor provides a
  real resumable UI flow without introducing deployment infrastructure.
- **No agent loop.** The order of retrieval calls does not depend on a model’s
  self-assessment. This bounds cost and makes failures reproducible.

## Assignment mapping

| Assignment objective | DealLens evidence |
|---|---|
| Meaningful value for a real workflow | Replaces manual first-pass adverse-event searching with a cited, reviewable acquisition screen |
| Tavily used deeply | Research for recall, Search for baseline/verification/entity resolution, Extract for evidence capture |
| Retrieval quality | Four-category coverage, trusted-domain filters, exact registry entity checks, focused extraction |
| Source handling and citations | Publisher normalization, verbatim quote validator, atomic assertion relationships, clickable URLs |
| Evaluation loop | `deallens eval`, 36 labelled cases, case-level baseline deltas, reviewed promotion, CI artifact |
| Context engineering | Kimi receives bounded snippets/query-focused chunks rather than an uncontrolled web corpus |
| Observability | LangSmith root/child trace contract plus per-run Tavily/Nebius/latency ledger |
| Customer adaptation | YAML jurisdiction tiers and two acquisition severity profiles |
| Small thing done well | One target, four categories, one memo; explicit exclusions and limitations |
| Required LLM provider | Nebius Token Factory + Kimi K3; no Claude runtime path |

## Honest limitations

DealLens cannot prove a clean bill of health, guarantee recall, resolve every
brand/group/legal-entity relationship, access sealed or paywalled records, or
replace professional diligence. It makes the public-web screening step faster,
more consistent, and materially easier to audit.
