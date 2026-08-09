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
    MERGE --> POST[Protected-main post-check]
    QUEUE[Open PR queue] --> POST
    LIVE[Live graph checks] --> POST
    POST --> MAIN[Protected main]
    SYN[Synthetic merge ref/status-only evidence] -. non-authoritative for source identity .-> GATE
```

Merge readiness is not protected-main acceptance. After explicit merge execution, the protected-main post-check revalidates the open PR queue, finding resolution, branch protection, and live graph state under `docs/RELEASE_ACCEPTANCE.md` before integrated behavior is treated as operational evidence.

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
