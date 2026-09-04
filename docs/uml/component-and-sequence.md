# Component and sequence views

## Authority

These diagrams describe protected-main composition. They do not add runtime
authority and do not promote ACTIVE-PR backup, restore, discovery, or worker
lanes into shipped components.

## What to do next

1. Deploy this package alone, or embed it behind `contextual-orchestrator` /
   `naruon` after those hosts authenticate and authorize.
2. Inject credentials and `tenant_scope` from the host. Do not read them from
   provider responses.
3. Call `DurableBatchAPIClient` for `standalone`. Call
   `TenantDurableBatchAPIClient` only after the host has chosen a scope.

## Component view

```mermaid
flowchart LR
    subgraph hosts [Optional CWL hosts]
        orchestrator[contextual-orchestrator]
        naruon[naruon]
    end
    subgraph package [pg-llm-batch standalone or embedded]
        cli[cli.py]
        durable[DurableBatchAPIClient]
        tenant[TenantDurableBatchAPIClient]
        client[batch_api_client.py]
        reconcile[reconciliation.py]
        db[db.py]
        checkpoints[checkpoint_store.py]
        evidence[recovery evidence modules]
    end
    postgres[(PostgreSQL)]
    provider[OpenAI-compatible Batch API]
    orchestrator -->|authorized tenant_scope| tenant
    naruon -->|authorized tenant_scope| tenant
    cli --> durable
    durable -->|standalone| db
    tenant -->|set_config tenant_scope| db
    durable --> client
    tenant --> client
    reconcile --> client
    db --> postgres
    checkpoints --> postgres
    client --> provider
    evidence -.->|hash and receipt only| postgres
```

`contextual-orchestrator` and `naruon` are optional. The package must keep
working when they are absent.

## Tenant lifecycle sequence

```mermaid
sequenceDiagram
    participant Host
    participant TenantClient as TenantDurableBatchAPIClient
    participant DB as db.py
    participant PG as PostgreSQL
    participant Provider as Batch API
    Host->>TenantClient: construct(tenant_scope)
    TenantClient->>TenantClient: validate tenant_scope
    Host->>TenantClient: observe or persist remote batch
    TenantClient->>DB: parameterized set_config(tenant_scope)
    DB->>PG: transaction-local scope plus RLS
    TenantClient->>Provider: bounded upload/create/poll/retrieve
    Provider-->>TenantClient: untrusted status and files
    TenantClient->>DB: tenant-qualified upsert
    DB->>PG: (tenant_scope, endpoint_alias, remote_batch_id)
```

A missing or malformed scope fails before credential lookup, provider I/O, or
lifecycle SQL. `DurableBatchAPIClient` keeps the four-argument recorder seam
and stores under the exact `standalone` scope.
