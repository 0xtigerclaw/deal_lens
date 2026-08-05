# Architecture

This document defines the runtime components, trust boundaries, retrieval
sequence, failure semantics, and LangSmith span structure for DealLens.
Tavily-owned retrieval components are highlighted in orange in every diagram
where they participate.

## 1. System context

```mermaid
flowchart TB
    Analyst["Acquisition analyst"]
    UI["Dependency-free web UI"]
    API["FastAPI job + archive API"]
    Worker["Bounded background worker"]
    Config["Jurisdiction + severity YAML"]
    Tavily["Tavily<br/>Research · Search · Map · Extract"]
    Nebius["Nebius Token Factory<br/>Kimi K3"]
    Gate["Deterministic evidence gate"]
    Artifacts["Local memo.md + evidence.json<br/>memo.pdf on demand"]
    LS["LangSmith EU project"]

    Analyst --> UI --> API
    API -->|"entity lookup"| Tavily
    API --> Worker
    Config --> Worker
    Worker --> Tavily
    Worker --> Nebius
    Worker --> Gate
    Gate --> Artifacts
    API --> Artifacts
    Worker -. "traces" .-> LS
    Tavily -. "nested spans" .-> LS
    Nebius -. "nested spans" .-> LS

    classDef tavily fill:#fff0e8,stroke:#f0522d,stroke-width:3px,color:#70230f
    class Tavily tavily
```

The web layer renders the typed `ScreenResult`; it does not reproduce the
evidence gate in JavaScript. A failed worker has no clean result object and is
rendered as a failure state.

## 2. Retrieval and decision pipeline

```mermaid
flowchart TD
    I["Confirmed target<br/>name · domain · company ID · jurisdiction"]
    R["Tavily /research<br/>recall-first candidate hypotheses"]
    S0["Tavily /search × 5<br/>topic · recency · country-aware"]
    MAP["Tavily /map<br/>first-party disclosure URLs"]
    MX["Tavily /extract<br/>mapped disclosure chunks"]
    N["Kimi K3<br/>normalize candidates + interpret snippets"]
    M["Deterministic candidate merge<br/>category + token Jaccard"]
    SV["Tavily /search<br/>trusted source tiers"]
    SR["Tavily /search<br/>exact registry entity when relevant"]
    P["Deterministic URL selection<br/>primary first · max 3"]
    X["Tavily /extract<br/>claim-focused chunks"]
    Q["Kimi K3<br/>copy quote + map assertions"]
    V["Deterministic validators<br/>verbatim · tier · publisher · entity"]
    G["Assertion evidence gate"]
    Y["YAML severity policy"]
    O["ScreenResult<br/>PDF/Markdown memo + JSON + usage"]

    I --> R --> N
    I --> S0 --> N
    I --> MAP --> MX --> N
    N --> M
    M --> SV
    M --> SR
    SV --> P
    SR --> P
    P --> X --> Q --> V --> G
    Y --> G --> O

    classDef tavily fill:#fff0e8,stroke:#f0522d,stroke-width:3px,color:#70230f
    class R,S0,MAP,MX,SV,SR,X tavily
```

### Component contracts

| Boundary | Accepts | Produces | May not do |
|---|---|---|---|
| Research | target identity, category prompt | candidate hypotheses | award evidence status |
| Baseline Search | category topic/recency policy, jurisdiction country boost, configured domains | snippets and URLs | use country boosting for non-general topics or treat empty results as clean |
| First-party Map | target domain, bounded disclosure instructions | relevant same-domain URLs | treat a company statement as independent verification |
| Verification Search | candidate query, source governance | candidate source set | bypass exclusions or entity mismatch |
| Extract | up to three selected URLs, claim query | focused page content + failed URLs | hide failed extraction |
| Kimi quote selection | extracted content, atomic assertions | copied passage and relationship indexes | rewrite a passage or decide verification |
| Evidence gate | validated typed evidence | finding status and risk roll-up | call providers or use model confidence |

## 3. New-user entity confirmation

```mermaid
sequenceDiagram
    actor A as Analyst
    participant UI as Web UI
    participant API as Entity API
    box rgb(255, 240, 232) Tavily retrieval
    participant T as Tavily Search
    end
    participant R as Local ranker
    participant W as Screen worker

    A->>UI: Enter company + website
    UI->>API: POST /api/entities/resolve
    API->>T: Search only configured registry domain
    T-->>API: Registry URLs, titles, scores
    API->>R: Parse IDs, normalize names, rank, abstain
    R-->>UI: 0–3 candidates (no automatic selection)
    alt analyst confirms a candidate
        A->>UI: Confirm and run
        UI->>W: Start screen with legal name + company ID
    else analyst explicitly skips
        A->>UI: Continue without registry match
        UI->>W: Start screen with company ID omitted
    else no action
        Note over UI,W: No paid screen starts
    end
```

The ranker accepts only exact configured registry hosts and canonical
Companies House `/company/{id}` paths. Low similarity, malformed paths, empty
titles, off-domain hosts, and duplicate IDs are rejected.

## 4. Evidence state machine

```mermaid
flowchart TD
    C["Candidate with atomic assertions"] --> E{"Any valid qualifying evidence?"}
    E -->|"no + retrieval/classification failure"| U["UNRESOLVED"]
    E -->|"no failure, no evidence"| R["REJECTED"]
    E -->|"yes"| X{"Support and contradiction?"}
    X -->|"both"| F["CONFLICTING"]
    X -->|"contradiction only"| D["CONTRADICTED"]
    X -->|"support"| A{"All assertions covered?"}
    A -->|"no"| P["PARTIAL"]
    A -->|"yes"| T{"Every assertion meets<br/>primary or 2-publisher threshold?"}
    T -->|"yes"| V["VERIFIED"]
    T -->|"no, but each has secondary support"| RP["REPORTED"]
```

Severity is evaluated only after status. A high-severity report may escalate
the overall screen to `REVIEW REQUIRED`, but severity cannot upgrade evidence
from Reported to Verified.

## 5. Failure semantics

```mermaid
flowchart LR
    Failure["Failure"] --> Search["Tavily Search fails"]
    Failure --> Map["Tavily Map fails"]
    Failure --> Extract["Tavily Extract fails / blocked"]
    Failure --> Model["Kimi structured output fails"]
    Failure --> Narrative["Narrative generation fails"]

    Search --> Job["Job fails safely or category is review-required"]
    Map --> Continue["External governed screening continues<br/>Map status = failed"]
    Extract --> Unresolved["Candidate = UNRESOLVED<br/>failed URL retained"]
    Model --> Review["Category/claim = REVIEW REQUIRED"]
    Narrative --> Evidence["Validated evidence retained<br/>fallback prose used"]

    classDef tavily fill:#fff0e8,stroke:#f0522d,stroke-width:3px,color:#70230f
    class Search,Map,Extract tavily
```

Missing observations are never converted to negative findings. The only clean
category state is `checked_no_finding`, which requires at least one completed
governed check and no surfaced qualifying finding or processing failure.

## 6. Data lineage

```mermaid
flowchart LR
    TR["Tavily Research response"] --> Candidate
    TS["Tavily Search result"] --> Candidate
    TM["Tavily Map URLs"] --> FirstParty["First-party candidate"]
    FirstParty --> Candidate
    Candidate --> Assertion["Atomic assertions"]
    TS --> URL["Governed URL"]
    URL --> Content["Tavily Extract content"]
    Content --> Quote["Verbatim quote"]
    Quote --> Relationship["supports[] / contradicts[]"]
    Assertion --> Relationship
    Relationship --> Finding
    Candidate --> Provenance["Typed Tavily provenance"]
    Content --> Provenance
    Finding --> Coverage
    Finding --> Risk
    Coverage --> Result["ScreenResult JSON"]
    Risk --> Result
    Provenance --> Result
    Result --> Memo["IC memo<br/>styled PDF + Markdown"]

    classDef tavily fill:#fff0e8,stroke:#f0522d,stroke-width:3px,color:#70230f
    class TR,TS,TM,Content tavily
```

Every displayed source relationship survives in `evidence.json`, including
Tavily method/endpoint/query/relevance, retrieval time, URL, configured
publisher identity, source tier, quote, assertion indexes, claim-scoped
credits, extraction failures, and processing failures. First-party evidence is
typed separately and cannot independently satisfy the verification gate.
General-search provenance also records the country boost selected by the
jurisdiction pack.

## 7. LangSmith trace tree

```mermaid
flowchart TB
    Root["deallens.screen<br/>root metadata + final usage/outcome"]
    Root --> Discover["deallens.discover"]
    Discover --> Research["tavily.research"]
    Discover --> Normalize["ChatNebius · optional normalization"]
    Root --> FirstParty["deallens.first_party_discovery"]
    FirstParty --> Map["tavily.map"]
    FirstParty --> MapExtract["tavily.extract"]
    FirstParty --> MapLLM["ChatNebius disclosure candidates"]
    Root --> Baseline["deallens.baseline_checks"]
    Baseline --> Search4["tavily.search × 5"]
    Root --> Interpret["deallens.discover_from_baseline"]
    Interpret --> LLM1["ChatNebius per non-empty category"]
    Root --> Verify["deallens.verify × candidate"]
    Verify --> SearchN["tavily.search × 1–2"]
    Root --> Capture["deallens.capture × candidate"]
    Capture --> ExtractN["tavily.extract"]
    Capture --> LLM2["ChatNebius quote mapping"]
    Root --> NarrativeN["ChatNebius narrative"]

    Entity["deallens.resolve_entity<br/>separate pre-confirmation trace"] --> EntitySearch["tavily.search"]

    classDef tavily fill:#fff0e8,stroke:#f0522d,stroke-width:3px,color:#70230f
    class Research,Map,MapExtract,Search4,SearchN,ExtractN,EntitySearch tavily
```

Tests force `LANGSMITH_TRACING=false`; only explicit live operations enter the
`Deal_Lens` project.

## 8. Evaluation feedback loop

```mermaid
flowchart LR
    Review["Live screen or analyst review"] --> Label["Human-labelled failure fixture"]
    Label --> Harness["Production gate/ranker/governance eval"]
    Baseline["Committed case-level baseline"] --> Delta["Behavior + coverage delta"]
    Harness --> Delta
    Delta -->|"regression"| Fix["Production-code fix"]
    Fix --> Harness
    Delta -->|"all gates hold"| Promote["Reviewed baseline promotion"]
    Promote --> Baseline
    Delta --> CI["CI gate + retained JSON artifact"]
```

The harness uses model or analyst judgment only to establish the expected
label. Verification is deterministic and offline. A case deletion is treated
as a regression, duplicate case names are rejected, and promotion cannot occur
while a behavioral or safety-metric gate fails.

## 9. Persistence and concurrency

- `ThreadPoolExecutor(max_workers=2)` bounds local concurrent live screens.
- The public Cloud Run profile sets
  `DEALLENS_REQUIRE_PERSONAL_TAVILY_KEY=true`: entity resolution and new live
  screens require a request header and never fall back to a project-funded
  Tavily credential. The browser retains the request key only in page memory,
  sends it only to endpoints that call Tavily, and clears it on refresh or tab
  close. The key is omitted from job payloads and removed from the queued job
  as soon as the worker claims it; no key fingerprint is retained.
- API responses use `Cache-Control: no-store`. A restrictive Content Security
  Policy and companion referrer, framing, MIME-sniffing, and browser-permission
  headers reduce client-side credential exposure.
- `DEALLENS_LIVE_SCREEN_LIMIT=12`, one Cloud Run instance, and concurrency two
  bound server-funded Nebius exposure per container lifetime. Archived memos
  and the deterministic fixture do not consume that allowance.
- Jobs persist in process for progress/resume; completed outputs persist on
  disk beneath ignored `reports/web/{job_id}` directories.
- The archive discovers the latest output per legal entity and also serves five
  committed public examples from `examples/screens`. Both archived and newly
  completed screens expose PDF and Markdown memo downloads; PDFs are generated
  from the same typed `ScreenResult` used by the UI and JSON evidence package.
- This is intentionally single-node MVP infrastructure. A production service
  would move job state to a durable queue/database without changing the typed
  pipeline or evidence gate.
