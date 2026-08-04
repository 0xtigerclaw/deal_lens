# Build log

This is the concise record of the product and engineering decisions that led
to the submitted DealLens repository. The implementation was developed with AI
coding assistance and continuously verified through source inspection, unit
tests, offline evals, API smoke tests, live provider runs, and UI review.

## 1. Problem selection

The initial exploration considered a general change-intelligence monitor. The
scope was deliberately narrowed to one transaction workflow with an immediate
output: enter one target and receive a source-backed public red-flag screen.

The selected user is an acquisition/search-fund analyst screening UK private
companies before commissioning full diligence. The four categories are fixed:
leadership/ownership, regulatory/litigation, cybersecurity, and financial
distress.

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
- retained Wise and Revolut example screens;
- a result workspace for claims, coverage, sources, assertions, and usage; and
- Markdown/JSON downloads.

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

Final measured result on 2026-08-04: **36/36**, false verifies **0/11**,
correct entity abstentions **4/4**. The surrounding pytest suite passes
**73/73** tests. Both commands are CI gates.

The eval command now emits stable case-level reports and compares them with a
committed reviewed baseline. It fails on behavior regressions, false-verify or
abstention degradation, and removed fixture coverage. An explicit `--promote`
step updates the baseline only after every gate passes; CI retains the report
as a downloadable artifact even when the gate fails.

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

## 9. Known next work

1. Build an analyst-labelled live-target eval for open-web recall.
2. Detect syndicated/near-duplicate articles across publisher domains.
3. Add tested entity adapters for non-UK registries.
4. Persist multi-user jobs in a queue/database for deployment.
5. Add human dispositions so accepted/rejected findings feed future eval sets.
