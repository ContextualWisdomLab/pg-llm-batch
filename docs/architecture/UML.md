# UML and behavior views

## Status and authority

This document is **ACTIVE-PR** until the documentation PR reaches protected `main`. Nodes labelled `IMPLEMENTED-ON-PROTECTED-MAIN` describe behavior present on protected `main` at the documentation baseline; nodes labelled `ACTIVE-PR` describe open implementation work and are not shipped claims.

## 1. Protected-main component topology

```mermaid
flowchart LR
    CLI[CLI\nIMPLEMENTED-ON-PROTECTED-MAIN] --> ORCH[PostgresBatchOrchestrator\nIMPLEMENTED-ON-PROTECTED-MAIN]
    ORCH --> CFG[Postgres config + secret stores\nIMPLEMENTED-ON-PROTECTED-MAIN]
    ORCH --> TOK[pg_tiktoken token counter\nIMPLEMENTED-ON-PROTECTED-MAIN]
    ORCH --> DB[(PostgreSQL schema\nIMPLEMENTED-ON-PROTECTED-MAIN)]
    CLI --> API[BatchAPIClient\nIMPLEMENTED-ON-PROTECTED-MAIN]
    API --> CRED[CredentialsProvider\nIMPLEMENTED-ON-PROTECTED-MAIN]
    CRED --> CFG
    API --> REMOTE[OpenAI-compatible Files/Batches endpoint\nEXTERNAL]
    API --> DB
    HEALTH[/healthz\nIMPLEMENTED-ON-PROTECTED-MAIN] --> DB
```

## 2. Batch preparation sequence

```mermaid
sequenceDiagram
    participant U as Caller/CLI
    participant O as PostgresBatchOrchestrator
    participant C as PostgresConfigStore
    participant T as TokenCounter
    participant P as PostgreSQL
    U->>O: prepare_batches(...)
    O->>P: read queued requests
    O->>C: load governed configuration
    O->>T: count tokens
    T->>P: pg_tiktoken operations
    O->>O: partition requests into bounded payloads
    O->>P: persist payload document
    O->>P: persist batch file
    O->>P: persist JSONL lines
    O->>P: assign queued requests
    O->>P: update batch totals
    O->>P: commit preparation transaction
    P-->>O: durable identifiers
    O-->>U: prepared batch metadata
    Note over O,P: Any failure before commit rolls back this preparation transaction.
```

## 3. Provider request, retry, and response handoff

```mermaid
stateDiagram-v2
    [*] --> ValidateDestination
    ValidateDestination --> AcquireResponse: trusted endpoint + credentials
    AcquireResponse --> RetryDelay: retryable GET acquisition failure/status
    RetryDelay --> AcquireResponse: bounded attempts remain
    AcquireResponse --> HandedOff: response returned to caller
    AcquireResponse --> Failed: permanent/non-retryable or budget exhausted
    HandedOff --> ConsumeBoundedBody
    ConsumeBoundedBody --> Complete
    ConsumeBoundedBody --> FailedAfterHandoff: payload/close failure; no replay
    Complete --> [*]
    Failed --> [*]
    FailedAfterHandoff --> [*]
```

Protected-main retry authority is the code in `pg_llm_batch/batch_api_client.py`; ACTIVE-PR #71 changes the reviewed GET status/error-classification contract and must not be read as shipped until merged.

## 4. Durable remote lifecycle sequence

```mermaid
sequenceDiagram
    participant H as Host
    participant D as DurableBatchAPIClient
    participant R as Remote provider
    participant P as PostgreSQL
    H->>D: submit/poll operation
    D->>P: reserve observation order
    D->>R: bounded provider request
    R-->>D: provider snapshot
    D->>D: validate identifiers + normalize metadata
    D->>P: persist llm_remote_batch_jobs snapshot
    P-->>D: durable accepted state
    D-->>H: curated lifecycle result
```

Tenant-qualified lifecycle and forced-RLS behavior are **ACTIVE-PR** #53 overlays, not protected-main behavior.

## 5. Result streaming and checkpoint overlay

```mermaid
flowchart TD
    A[Aggregate result download\nIMPLEMENTED-ON-PROTECTED-MAIN] --> R[Bounded provider response]
    R --> M[Whole aggregate materialization within configured bound]
    R -. ACTIVE-PR #58 .-> S[Incremental BatchResultRecord stream]
    S -. ACTIVE-PR #59 .-> C[Prefix-bound BatchResultCheckpoint]
    C -. ACTIVE-PR #60 .-> CP[(llm_result_stream_checkpoints)]
    CP -. ACTIVE-PR #92 .-> OBS[Checkpoint telemetry]
    OBS -. ACTIVE-PR #94 .-> AUD[Append-only checkpoint audit evidence]
    AUD -. ACTIVE-PR #95 .-> MIG[Atomic checkpoint migration operator]
    MIG -. ACTIVE-PR #96 .-> PAGE[Bounded stable audit pages]
    PAGE -. ACTIVE-PR #97 DRAFT .-> MAN[Snapshot-manifest assurance]
    OLD[#78 / #79 / #80 / #83 / #84\nSUPERSEDED] -. no evidence transfer .-> OBS
```

The live replacement order is #92 -> #94 -> #95 -> #96 -> #97. The former #78/#79/#80/#83/#84 chain is **SUPERSEDED**; its checks, reviews, approvals, and base evidence do not transfer to replacement heads. #97 is the current Draft snapshot-manifest successor.

## 6. Health/readiness deployment sequence

```mermaid
sequenceDiagram
    participant O as Operator / probe
    participant H as health server
    participant P as PostgreSQL
    O->>H: GET /healthz
    H->>P: pg_llm_batch_health_check()
    P-->>H: component rows
    H-->>O: readiness response
    Note over H: Protected-main implementation exists; #70/#91 harden public redaction, request bounds, listener and Compose exposure.
```

## 7. Evidence and merge authority

```mermaid
flowchart LR
    SRC[Exact contributor head] --> CI[CI/security checks]
    BASE[Independently resolved live base tip] --> COMP[Compatibility/ancestry]
    SRC --> REV[Semantic review]
    CI --> GATE[Merge readiness]
    COMP --> GATE
    REV --> GATE
    FIND[Finding resolution] --> GATE
    BP[Branch protection] --> GATE
    APP[Qualifying independent formal approval] --> GATE
    GATE -->|all policy gates satisfied on unchanged head| MERGE[Merge execution]
    MERGE --> MAIN[Protected main exact integrated revision]
    MAIN --> POST[Post-merge operational acceptance]
    QUEUE[Open PR queue revalidation] --> POST
    LIVE[Live graph / finding / branch-policy checks] --> POST
    POST --> ACCEPT[Operational acceptance evidence]
    SYN[Synthetic merge ref/status-only evidence] -. non-authoritative for source identity .-> GATE
```

Merge readiness is not protected-main acceptance. Explicit merge execution first creates the exact integrated protected revision. This protected-main post-check is the capability-specific post-merge operational acceptance: it revalidates the applicable queue, findings, branch policy, live graph, runtime/deployment/migration/operator behavior, and other evidence required by `docs/automation/ADR-0005-protected-main-operational-acceptance.md` and `docs/RELEASE_ACCEPTANCE.md`. Only that fresh evidence may close the applicable incident/runtime/release acceptance lane; the merge itself is intermediate.

## 8. Standalone and CWL composition

```mermaid
flowchart TB
    subgraph Standalone
      APP[Host/CLI]
      PG[(PostgreSQL)]
      APP --> PG
    end
    subgraph External
      PROVIDER[OpenAI-compatible provider]
    end
    APP --> PROVIDER
    subgraph OptionalCWL[Optional CWL composition]
      ORCH[contextual-orchestrator\nread-only dependency from this repo loop]
      CENTRAL[organization .github reusable automation\nread-only dependency]
    end
    APP -. versioned/provider-neutral integration .-> ORCH
    CENTRAL -. CI/review control plane .-> APP
```

No CWL service owns pg-llm-batch application tables by direct cross-service database access. Host integrations must use explicit interfaces and preserve standalone operation.

## 9. Scheduler failure recovery

The autonomous writer is an external control plane, not a pg-llm-batch application-table owner. A **generic scheduled-task failure** therefore begins as control-plane incident evidence; it is not a repository failure until independent repository evidence establishes one.

```mermaid
flowchart TD
    START[Hourly scheduler invocation] --> EXEC[Execute live pg-llm-batch queue]
    EXEC --> OK[Repository action / proof / defer decision]
    EXEC --> FAIL[Generic scheduled-task failure]
    FAIL --> REFRESH[Refetch authoritative scheduler + GitHub state]
    REFRESH --> CLASSIFY{First failing boundary}
    CLASSIFY --> SCHED[Scheduler / activation]
    CLASSIFY --> PROMPT[Prompt size / transport]
    CLASSIFY --> TOOL[Tool / connector]
    CLASSIFY --> AUTH[Credential / permission]
    CLASSIFY --> DEP[Read-only dependency]
    CLASSIFY --> REPO[Repository behavior]
    SCHED --> REPAIR[Smallest feasible control repair]
    PROMPT --> COMPACT[Compact obsolete prompt history]
    TOOL --> REPAIR
    AUTH --> DEFER[Defer only affected lane]
    DEP --> DEFER
    REPO --> RCA[Repository RCA / test-first repair]
    COMPACT --> REPAIR
    REPAIR --> NODUP[Retain one authoritative scheduler; no duplicate scheduler]
    NODUP --> SAME[Resume material repository work in same invocation]
    RCA --> SAME
    DEFER --> SAME
    OK --> SAME
    SAME --> SWEEP1[Double exit sweep 1]
    SWEEP1 -->|safe work exists| EXEC
    SWEEP1 -->|no safe work| SWEEP2[Double exit sweep 2]
    SWEEP2 -->|safe work exists| EXEC
    SWEEP2 -->|none / practical budget exhausted| END[End invocation]
```

ADR-0006 owns this scheduler failure recovery decision. Prompt or scheduler repair is intermediate and does not waive source, review, branch-protection, security, or release gates. Scheduler state remains operational evidence outside the product ERD; `docs/architecture/ERD.md` intentionally does not invent automation persistence.
