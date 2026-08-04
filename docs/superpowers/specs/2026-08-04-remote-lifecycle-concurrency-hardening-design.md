# Durable Remote Lifecycle Concurrency Hardening Design

## Context

PR #50 introduces `DurableBatchAPIClient` and `llm_remote_batch_jobs` for restart-safe provider lifecycle state. Its first implementation timestamps an observation inside `persist_remote_batch_state()` after the provider response has returned, then rejects only rows with an older timestamp.

That does not protect overlapping polls. Consider two requests for the same remote batch:

1. poll A starts first and receives an older provider snapshot, but its response is delayed;
2. poll B starts later, returns first, and persists a newer snapshot;
3. poll A finally returns and receives a later local persistence timestamp;
4. the SQL predicate accepts poll A and regresses the stored status.

The timestamp currently represents completion/persistence order, not request order. The documented claim that a delayed poll cannot regress a newer state is therefore not yet supported by the implementation.

A second integrity boundary exists after a terminal state. A provider batch in `completed`, `failed`, `expired`, or `cancelled` must not return to a non-terminal or different terminal status. Later observations with the same terminal status may still enrich file identifiers, request counts, or metadata.

Finally, provider metadata is untrusted. A mapping can contain non-JSON values, non-finite numbers, cycles, or enough content to create an acquisition-visible database growth problem. The durable store should retain curated bounded metadata rather than turn those values into raw serialization or database failures.

## Goals

- Establish globally ordered observation tickets before remote provider calls.
- Ensure a delayed earlier request cannot overwrite a later-started request across client instances sharing the same PostgreSQL store.
- Make terminal status identity immutable while allowing same-terminal enrichment.
- Fail before side-effecting remote operations when durable observation ordering cannot be reserved.
- Include the observation order and failure phase in recovery-oriented errors.
- Bound persisted metadata to 64 KiB of canonical UTF-8 JSON and reduce invalid metadata to `{}`.
- Preserve the base `BatchAPIClient` contract and its single-attempt POST behavior.
- Keep all database object names descriptive multi-word `snake_case`.
- Retain 100% production statement, branch, and docstring coverage.

## Non-goals

- Persisting complete provider responses.
- Persisting token usage or provider-specific timestamp fields in this slice.
- Changing retry statuses, attempt limits, or download limits.
- Guaranteeing monotonic progression for unknown non-terminal provider statuses.
- Replacing PostgreSQL as the default lifecycle store.

## Approaches considered

### 1. Timestamp each response after it arrives

This is the current implementation. It orders persistence completion, so it cannot distinguish a delayed old response from a genuinely newer request. Rejected.

### 2. Capture the application host clock before each request

Capturing `datetime.now(timezone.utc)` before the network call fixes overlap within a well-synchronized host, but distributed workers may have clock skew. It also makes correctness depend on host time configuration. Rejected as the default commercial contract.

### 3. Reserve a PostgreSQL sequence value before each request — selected

Create `llm_remote_batch_observation_sequence` and reserve `nextval(...)` before every durable create, poll, or cancellation request. The sequence is shared by all clients using the database and is independent of transaction rollback, so later-started durable requests receive a strictly larger order.

The upsert accepts only an `EXCLUDED.observation_order` greater than the stored order. An earlier request that completes later therefore cannot overwrite a later-started request. Sequence gaps caused by failed requests are harmless and expected.

This adds one lightweight database round trip before each durable provider operation. That cost is explicit and appropriate for the opt-in durable client; hosts that own another ordering mechanism may inject a compatible reserver and recorder.

### 4. Rank provider statuses only

A fixed status rank can prevent some regressions, but OpenAI-compatible gateways may add statuses and parallel branches such as cancellation. It also cannot order count or metadata enrichment within the same status. Status finality is useful as an additional invariant, not as the primary ordering primitive.

## Selected interfaces

### Database order reservation

```python
def reserve_remote_batch_observation_order(dsn: str) -> int:
    """Reserve and return a positive global lifecycle observation order."""
```

The function executes:

```sql
SELECT nextval('llm_remote_batch_observation_sequence')
```

It validates the returned value as a positive non-boolean integer.

### Persistence

```python
def persist_remote_batch_state(
    dsn: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
```

`observation_order` is required. The durable client always reserves it before the remote operation. Explicit direct callers must do the same, which avoids a misleading persistence-time fallback.

The table stores `observation_order BIGINT NOT NULL CHECK (observation_order > 0)`. Its conflict update predicate requires:

```sql
EXCLUDED.observation_order > llm_remote_batch_jobs.observation_order
```

and, when the stored row is terminal, requires the incoming terminal status to be identical.

### Durable client injection seams

```python
ObservationReserver = Callable[[str], int]
LifecycleRecorder = Callable[[str, str, Mapping[str, Any], int], Any]
```

`DurableBatchAPIClient` accepts both seams. Before calling a remote operation it reserves an order in a worker thread. After a successful accepted transition it passes the same order to the recorder.

## Failure contract

### Reservation failure

If reservation fails or returns an invalid value, the client raises `GatewayError` before the provider request. Structured data contains:

```json
{
  "operation": "Batch creation",
  "phase": "reservation",
  "endpoint_alias": "primary",
  "batch_id": null,
  "error_type": "OperationalError"
}
```

No remote side effect has occurred.

### Persistence failure after remote success

The client raises `GatewayError` with `phase: "persistence"`, the remote batch identifier when known, and the reserved observation order. It does not replay side-effecting POST operations.

## Terminal-state invariant

Terminal statuses are:

```text
completed, failed, expired, cancelled
```

A stored terminal row may be updated only by a later observation with the same status. This supports delayed availability of output/error files and final counts without permitting terminal regression or terminal identity changes.

## Metadata boundary

Provider metadata is retained only when it is a mapping that can be serialized with:

```python
json.dumps(
    metadata,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
)
```

The canonical UTF-8 representation must be at most `64 * 1024` bytes. Non-serializable, cyclic, non-finite, or excessive metadata is normalized to an empty object and canonical `{}` JSON. Arbitrary provider fields remain discarded.

## Testing

The hardening tests must first fail against the original PR head and cover:

- SQL schema and upsert order predicates;
- terminal-state immutability with same-terminal enrichment;
- reservation before provider invocation;
- delayed earlier request completion receiving a lower order than the already-recorded later request;
- reservation failure preventing a remote create call;
- persistence failure exposing phase and order;
- non-JSON, cyclic, non-finite, and over-limit metadata normalization;
- invalid observation order validation.

The complete Python matrix, 100% statement/branch/docstring coverage, package build, container builds, SAST, Security Scan, and review gates remain required on the final exact head.

## Documentation and standards

`docs/remote-batch-lifecycle.md` will describe the sequence reservation, terminal invariant, metadata limit, and failure phases. References will use APA 7th style and distinguish undated living API documentation with a retrieval date.

PostgreSQL documents `ON CONFLICT DO UPDATE` as an atomic insert-or-update outcome under concurrency. Sequence `nextval` supplies a database-owned strictly increasing reservation order. OpenAI's current Batch object documents the stored identifiers, status, file fields, request counts, metadata, and terminal/cancellation behavior.
