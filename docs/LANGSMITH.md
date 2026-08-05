# LangSmith observability

DealLens uses LangSmith as the debugging and audit layer for live provider
operations. Tracing is optional for the offline demo and mandatory for the
submission/live verification path.

## Configuration

```env
LANGSMITH_TRACING="true"
LANGSMITH_API_KEY="lsv2_..."
LANGSMITH_PROJECT="Deal_Lens"
LANGSMITH_ENDPOINT="https://eu.api.smith.langchain.com"
```

The configured project uses LangSmith’s EU endpoint. A key issued for an EU
workspace must be sent to that endpoint.

Check configuration without exposing secrets:

```bash
curl -s http://127.0.0.1:8000/api/health | jq .observability
```

Expected shape:

```json
{
  "enabled": true,
  "project": "Deal_Lens",
  "region": "EU",
  "root_span": "deallens.screen"
}
```

## Trace contract

One completed live screen should create one root chain named
`deallens.screen`, tagged:

- `production-screen`
- `governed-evidence`
- `nebius-kimi-k3`

Static root metadata:

- `pipeline_version`
- `model_provider`
- `model_family`
- `retrieval_provider`

Dynamic input metadata:

- `target`
- `domain`
- `company_id_supplied`
- `jurisdiction`

Dynamic outcome metadata:

- `risk_level`
- `candidate_count`
- `finding_count`
- `verified_count`
- `review_required_categories`
- `tavily_credits`
- `tavily_credits_by_endpoint`
- `retrieval_contribution`
- `llm_input_tokens`
- `llm_output_tokens`
- `wall_seconds`

Child spans identify the expensive/failure-prone stages:

```text
deallens.screen
├── deallens.discover
│   ├── tavily.research
│   └── ChatNebius (only if response normalization is needed)
├── deallens.first_party_discovery
│   ├── tavily.map
│   ├── tavily.extract
│   └── ChatNebius
├── deallens.baseline_checks
│   └── tavily.search × 5
├── deallens.discover_from_baseline
│   └── ChatNebius × non-empty category
├── deallens.verify × candidate
│   └── tavily.search × 1–2
└── deallens.capture × candidate
    ├── tavily.extract
    └── ChatNebius (quote mapping)
```

Short narrative generations also appear as Nebius model children. Legal-entity
lookup is deliberately a separate `deallens.resolve_entity` trace with the
tags `entity-resolution` and `human-confirmation-required`; it occurs before a
user authorizes a full screen.

The committed `langsmith-verification.json` is the historical v0.2 live run.
It remains evidence of that run rather than being rewritten to imply the v0.3
Map spans were observed; the next live verification should supersede it.

## Test isolation

`tests/conftest.py` sets both `LANGSMITH_TRACING=false` and
`LANGSMITH_TEST_TRACKING=false` before importing application modules. Unit
tests may use fake Tavily/Nebius objects, so allowing them into the live project
would create misleading latency, token, and quality data.

## Verification checklist

1. Start the server and check `/api/health` reports LangSmith enabled, project
   `Deal_Lens`, region `EU`.
2. Run one real confirmed target.
3. Open the latest `deallens.screen` root in LangSmith.
4. Confirm Research, four baseline searches, candidate verification, Extract,
   and Nebius calls are nested beneath the same root.
5. Compare root outcome metadata with the downloaded `evidence.json` usage and
   risk fields.
6. Confirm the trace contains no API keys or `.env` values.

Do not make a trace public without reviewing its target and evidence content.
The public repository documents the span contract; authenticated reviewers can
inspect the configured project during a demonstration.

## Verified submission run

The final end-to-end check completed on 2026-08-04 against `MONZO BANK LIMITED`
(company number `09446231`):

| Field | Observed value |
|---|---|
| Root trace | `019fcc59-bc35-71a0-9f3d-0604e152cb4e` |
| Status | `success` |
| Runtime | `191.089s` |
| Spans | `204` |
| Span errors | `0` |
| Tavily structure | 1 Research, 22 Search, 10 Extract spans |
| DealLens structure | 1 baseline, 10 verify, 10 capture spans |
| Nebius structure | 21 `ChatNebius` spans |
| Output | 10 candidates, 3 verified, `REVIEW REQUIRED` |
| Measured usage | 28 Tavily Search/Extract credits, 33,033 Kimi input tokens, 5,068 output tokens |

The root metadata and emitted `evidence.json` agree on candidate count, finding
count, risk level, token counts, measured credits, and wall time. When this run
completed, its Research delta had not yet appeared in Tavily's `/usage`
response, so the artifact conservatively set `usage_complete=false` instead of
overstating total cost. DealLens now reads the endpoint's dedicated
`research_usage` counter and briefly retries delayed updates.

The pre-confirmation live registry lookup is trace
`019fcc57-00a1-74f1-871c-2f877182bcb4`: `success`, 1.033s, tagged
`entity-resolution` and `human-confirmation-required`.

A machine-readable, secret-free snapshot of these checks is committed as
[langsmith-verification.json](langsmith-verification.json). The traces are not
made public because they contain a real target and extracted evidence; a
reviewer with project access can query the IDs above.
