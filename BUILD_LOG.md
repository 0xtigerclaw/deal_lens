# DealLens build record

## What this record proves

DealLens turns the assignment's generic search-agent starter into a bounded
acquisition-intelligence product. This record connects the product, retrieval,
correctness, and delivery decisions to their implementation and proof:

- **Product judgment:** two directions were tested against the assignment,
  Tavily depth, user specificity, evaluability, and delivery scope before
  DealLens was selected.
- **Retrieval engineering:** Tavily was separated into Research, adaptive
  Search, bounded Map, and focused Extract responsibilities, with jurisdiction
  boosts and source governance encoded outside prompts.
- **Correctness engineering:** live failures drove assertion-level evidence,
  verbatim quote checks, publisher independence, exact-entity filtering,
  contradiction states, and fail-closed category coverage.
- **Product delivery:** the same typed result powers the CLI, analyst UI,
  archive, live progress, and PDF/Markdown/JSON IC-memo exports.
- **Proof:** 84 tests, 36 labelled safety cases, zero false verifies in the
  adversarial set, correct entity abstention, CI, a live LangSmith run, a GCP
  deployment, and an auditable AI-development record.

The artifacts serve different reviewer questions:

| Artifact | What it demonstrates |
|---|---|
| [Reviewer build record](https://traces.com/s/jn79bwm0m5eq2j5s7v2186kf3s8bw9cn) | The shipped product, load-bearing architecture, safety boundary, v0.3 extension, and verification evidence in a short guided path |
| [Detailed build record](https://traces.com/s/jn776x8hyry34rr99q4k1tvscx8bvjjr) | The chronological decisions, implementation work, provider failures, corrections, eval growth, UI work, and shipping trail |
| This build log | The causal narrative connecting decisions to code and proof |
| [LangSmith contract](docs/LANGSMITH.md) | What actually happened inside a live provider run, including spans, failures, usage, tokens, and latency |

Together, they show not only what shipped, but why the architecture exists and
how it was tested against the mistakes most likely to mislead an investment
committee.

## Delivery snapshot

| Proof point | Result |
|---|---:|
| Product version | `0.3.0` |
| Python tests | **84/84 passed** |
| Labelled safety evaluation | **36/36 passed** |
| False verifies | **0/11** |
| Correct entity abstentions | **4/4** |
| Tavily responsibilities | Research · adaptive Search · bounded Map · focused Extract |
| v0.3 merge | PR [#7](https://github.com/0xtigerclaw/deal_lens/pull/7) · `07d7eaa` · CI passed |
| Historical live proof | v0.2 Monzo run · 204 LangSmith spans · 0 span errors |

The v0.3 retrieval work is merged into GitHub `main`. The committed LangSmith
snapshot remains the verified v0.2 run until a new live screen records Map and
country-aware Search; the historical artifact is not rewritten to imply those
spans already occurred.

## Build thesis and plan

**Objective:** turn the generic Tavily search agent into one bounded product:
an acquisition analyst enters a target and receives a current, source-backed
public-risk memo for investment committee preparation.

**Primary user:** a GP or acquisition analyst screening a UK private company
after initial interest and before specialist commercial, legal, financial, and
cybersecurity diligence.

**Scope:** one company, four fixed risk categories, one governed evidence
package, and one reviewable memo. Scheduling, deal recommendations,
multi-jurisdiction coverage, distributed infrastructure, and private-data
integrations remain outside the MVP.

**Execution sequence:**

1. Inspect the starter and assignment; replace the open-ended agent loop with
   a reproducible pipeline and typed boundaries.
2. Assign distinct Tavily responsibilities: Research for candidate recall,
   adaptive Search for category coverage, verification, and entity resolution,
   bounded Map for first-party discovery, and focused Extract for source
   capture.
3. Put trust decisions outside the model: confirm the legal entity, normalize
   publishers, validate quotes verbatim, evaluate atomic assertions, and apply
   status and severity rules deterministically.
4. Use Kimi K3 through Nebius only for bounded interpretation and memo prose;
   surface provider or retrieval failures as review states.
5. Integrate the flow into analyst work with entity confirmation, background
   progress, resumable screens, an archive, and PDF/Markdown/JSON exports.
6. Build the evaluation loop around the highest-cost errors: false
   verification, wrong-entity selection, and source-governance violations.
7. Trace one complete live run in LangSmith and reconcile its provider calls,
   tokens, credits, latency, and result with the emitted evidence artifact.
8. Package a clean public submission: reproducible commands, CI, architecture,
   technical statement, build record, live deployment, and short walkthrough.

**Exit criteria:**

- a fresh clone can run the fixture, tests, and evals without provider keys;
- a live screen covers all four categories and never treats missing evidence
  or a failed stage as clearance;
- every escalated quote is traceable to captured source content and the exact
  legal entity boundary is enforced where available;
- tests and labelled evals pass in CI with no false verification regression;
- LangSmith shows a successful Tavily/Nebius trace with a reconciled usage
  ledger; and
- the repository contains the implementation, technical statement, and a
  shareable record of the AI-assisted build, but not `starter_agent.py`.

This plan became the working contract for the build. Each material live failure
was converted into a code boundary or regression test rather than edited out of
the narrative.

## 1. Problem selection

The initial exploration considered a general change-intelligence monitor. The
scope was deliberately narrowed to one transaction workflow with an immediate
output: enter one target and receive a source-backed public red-flag screen.

The selected user is a GP or acquisition analyst preparing a target for
investment committee. The product enters the workflow after initial interest
and before full diligence: it assembles the current public evidence the analyst
needs for the memo, while preserving the source trail for risk and compliance
review. The four categories are fixed: leadership/ownership,
regulatory/litigation, cybersecurity, and financial distress.

The core product decision was made early: a generated research report was not
enough. Discovery and verification had to be separate, and “no result” could
not be presented as clearance.

## 2. First implementation and review

The first codebase established:

- Pydantic boundary models;
- Tavily Research, Search, and Extract wrappers;
- configurable jurisdiction/source tiers;
- candidate verification and extraction;
- a deterministic evidence gate;
- Markdown/JSON outputs; and
- CLI demo/eval commands.

Review found several issues that shaped the final architecture:

- Research’s asynchronous task had to be polled to completion rather than
  treating the initial task response as a report.
- Four category baselines were required because Research silence is not
  coverage.
- Exact dates and quantities had to survive claim decomposition.
- Registry documents needed exact company-number filtering.
- Failed extraction/model interpretation had to become unresolved/review
  states rather than disappear.
- Source independence had to use configured publisher identity rather than
  raw subdomains.

Each fix was encoded as a deterministic rule and regression test.

## 3. Provider requirement

The model path was migrated and documented to use Nebius Token Factory with
`moonshotai/Kimi-K3`. `langchain-nebius` is the runtime integration. Kimi’s
structured calls use JSON mode, temperature zero, low reasoning effort, a
bounded completion window, and two parse attempts.

The final repository has no Claude/Anthropic runtime dependency. Kimi performs
interpretation and prose only; verification and severity remain deterministic.

## 4. Product flow

A FastAPI layer and dependency-free HTML/CSS/JavaScript UI were added over the
same `ScreenResult` used by the CLI. The UX evolved from an expert form to:

- two required fields (company and website);
- optional advanced company number/jurisdiction/policy;
- known-company presets;
- background progress and job resume;
- retained Wise, Revolut, Monzo, Shell UK, and Starling example screens;
- a result workspace for claims, coverage, sources, assertions, and usage; and
- PDF/Markdown/JSON downloads.

The interface intentionally never recreates gate logic client-side.

## 5. Legal-entity resolution

The fifth submission improvement removed an expert-only assumption: new users
should not need to find a Companies House number before screening.

The implemented flow uses Tavily Search constrained to the registry domain,
parses canonical company URLs, ranks names locally, rejects malformed or
low-confidence results, and requires explicit human confirmation. No LLM
chooses the entity. “Continue without a registry match” remains possible but
must be an explicit action.

Regression coverage includes brand/legal names, exact matches, suffixes,
deduplication, unrelated results, spoofed domains, non-entity paths, empty
titles, and the API contract.

## 6. Evaluation hardening

The original gate eval was expanded into three independent suites:

- evidence gate + quote validation: 16 cases;
- legal-entity ranking: 8 cases; and
- source-governance contract: 12 cases.

Current measured result on 2026-08-05: **36/36**, false verifies **0/11**,
correct entity abstentions **4/4**. The surrounding pytest suite passes
**84/84** tests. Both commands are CI gates.

The eval command now emits stable case-level reports and compares them with a
committed reviewed baseline. It fails on behavior regressions, false-verify or
abstention degradation, and removed fixture coverage. An explicit `--promote`
step updates the baseline only after every gate passes; CI retains the report
as a downloadable artifact even when the gate fails.

GitHub-facing documentation now exposes the same loop in the README,
architecture, technical statement, PR validation summary, and CI workflow so
the evaluation claim is directly reproducible from a fresh clone.

## 7. LangSmith completion

LangSmith EU configuration was verified from environment/SDK access. The root
screen span was given stable tags plus input, outcome, provider, token, credit,
and latency metadata. Entity lookup is separately traced because it happens
before confirmation. Test tracing is disabled at import time to stop fake calls
from polluting the production project.

The final clean run screened `MONZO BANK LIMITED` in 191 seconds. LangSmith
recorded one successful root across 204 spans with zero span errors: one
Research call, 22 Search calls, 10 Extract calls, and 21 Kimi/Nebius model
calls. Root metadata matched the emitted evidence JSON for outcome, counts,
tokens, measured credits, and latency. The preceding live entity lookup was a
separate successful 1.033-second trace.

## 8. Submission packaging

The repository was curated for a reviewer who starts from a clean clone:

- complete README and quickstart;
- technical statement and explicit assignment mapping;
- GitHub-rendered Mermaid architecture diagrams;
- evaluation methodology and exact results;
- LangSmith span contract and checklist;
- committed, public example screens for the archive;
- `.env.example` with Tavily, Nebius/Kimi, and LangSmith EU variables; and
- CI for Python tests and deterministic evals.

MongoDB was deferred. Typed JSON/Markdown is the right persistence boundary for
this single-analyst MVP; database work would add submission surface without
improving the evidence contract.

## 9. Adaptive Tavily retrieval upgrade

The P0 retrieval work expanded Tavily from a uniform three-endpoint sequence
into four explicit, measurable responsibilities. This was an architectural
upgrade, not a prompt tweak:

- Research remains recall-first structured hypothesis generation.
- Baseline Search now chooses news, finance, or general topic and recency by
  risk category; candidate verification uses advanced search.
- Jurisdiction packs supply the country boost for general searches, improving
  local regulator, court, and regional-business recall without hardcoding UK
  logic into the pipeline.
- Map discovers bounded, same-domain first-party disclosures before focused
  Extract.
- Every claim and quote carries typed Tavily method, query, source, relevance,
  country, and claim-scoped credit provenance.
- Every result records an online retrieval ablation: Research candidates,
  incremental baseline and Map candidates, mapped URLs, validated evidence,
  surfaced claims, and credits per surfaced claim.

The safety boundary stayed deliberately asymmetric. A new `first_party` tier
can generate and support candidates but cannot independently verify them.
Country boosting can improve ranking but cannot override domain exclusions,
source tiers, publisher independence, entity matching, or assertion coverage.
Map failure is supplemental: it is recorded, while governed external screening
continues.

That work touched 34 files and added 1,421 lines across retrieval, typed models,
pipeline metrics, UI, memo/PDF rendering, examples, architecture, evaluation
documentation, and tests. It added eight tests without changing the labelled
safety result: 83/83 tests and 36/36 eval cases passed before merge.

## 10. BYO-key security hardening

The public reviewer flow was tightened after a focused credential-lifetime
review. The Tavily key now remains in JavaScript memory rather than Web Storage,
is sent only to endpoints that call Tavily, and must be re-entered after a page
refresh. The server no longer derives or retains a key fingerprint for active
job deduplication. API responses use `Cache-Control: no-store`, and every UI/API
response carries a restrictive Content Security Policy plus referrer,
clickjacking, MIME-sniffing, and browser-permission protections.

Regression coverage proves that the shipped JavaScript contains no
`sessionStorage` key path, health checks ignore supplied personal keys, API
responses are non-cacheable, and the CSP does not allow inline scripts. The
result is **84/84 tests passing** with the labelled safety evaluation unchanged
at **36/36**.

## 11. AI collaboration and trace deliverables

Development used two models with different responsibilities:

- **`fable`:** landscape and Tavily API research, product selection, scope
  review, and the initial offline evidence-gate core;
- **`gpt-5.6-sol`:** provider integration, correctness hardening, live runs,
  analyst UI, evaluations, observability, documentation, security, and GCP
  deployment.

The AI record is delivered as two complementary, credential-scrubbed Traces
artifacts. This is intentional: one raw chronology is too slow for a reviewer,
while one polished summary would hide the corrections and intermediate proof.

The primary [reviewer build
record](https://traces.com/s/jn79bwm0m5eq2j5s7v2186kf3s8bw9cn) is an
unlisted 32-event index grouped by reviewer question instead of chronology:

1. shipped product and proof snapshot;
2. user, workflow, and product decision;
3. explicitly rejected alternatives;
4. load-bearing Tavily architecture and deterministic evidence rules;
5. live provider integration and analyst workflow;
6. labelled evaluation and LangSmith span contracts;
7. deployment, public-demo security, and assignment mapping; and
8. the v0.3 Tavily retrieval extension with merge and validation proof.

The opening establishes the deployed v0.2 baseline: public repository, live
GCP service, 75 tests, 36 labelled evals, a successful 204-span LangSmith root,
and public-demo security. The August 5 extension then records the merged v0.3
retrieval architecture, 83 tests, unchanged safety gates, PR #7, and merge
commit `07d7eaa`. It explicitly distinguishes “merged” from “deployed.”
Selected source excerpts are labelled by model and original event number;
editorial summaries are explicit.

The public record was scanned locally and after upload for provider and GitHub
tokens, bearer credentials, email addresses, personal paths, and unrelated
workflow framing, with zero matches after redaction.

The [detailed standalone build
record](https://traces.com/s/jn776x8hyry34rr99q4k1tvscx8bvjjr) preserves
the chronological work across 1,550 rendered events: assignment and starter
review, product selection, provider integration, evidence correctness, analyst
workflow, evaluation, LangSmith observability, GCP deployment, final hardening,
and the v0.3 Tavily extension. It retains substantive prompts, implementation
updates, tool calls, and results while removing repetitive polling, hidden
reasoning, credentials, environment contents, personal paths, and unrelated
machine output.

The trace deliverable therefore exposes both the decision-quality summary and
the inspectable engineering trail. Together with this log, repository history,
[pull requests](https://github.com/0xtigerclaw/deal_lens/pulls?q=is%3Apr), and
the walkthrough, they make the build reproducible without allowing rejected
concepts or unverified claims to define the submitted product.

## 12. Known next work

1. Build an analyst-labelled live-target eval for open-web recall.
2. Detect syndicated/near-duplicate articles across publisher domains.
3. Add tested entity adapters for non-UK registries.
4. Persist multi-user jobs in a queue/database for deployment.
5. Add human dispositions so accepted/rejected findings feed future eval sets.
