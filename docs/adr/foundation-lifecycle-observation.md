# ADR: Database-owned lifecycle observation ordering and reconciliation

## Status and maturity

**IMPLEMENTED-ON-PROTECTED-MAIN.** This ADR records the protected-main `DurableBatchAPIClient` and `llm_remote_batch_jobs` authority boundary. Tenant-qualified lifecycle state in ACTIVE-PR #53 and checkpoint/audit work in later PRs are not promoted to shipped behavior by this decision.

## Context and decision drivers

A provider create, poll, or cancellation request and a PostgreSQL persistence write cannot participate in one ACID transaction. The external provider may succeed while local persistence fails, and concurrent observations need a deterministic package-owned ordering so stale responses do not silently overwrite newer durable lifecycle evidence.

The product therefore needs a lifecycle model that fails before provider I/O when local ordering authority cannot be obtained, but that truthfully represents the opposite split—provider success followed by database persistence failure—as a reconciliation condition rather than pretending the external effect never happened.

## Alternatives considered

1. **No package-owned lifecycle persistence.** Kept as an available base-client mode for hosts that own persistence, but insufficient as the package's durable option.
2. **Persist an intended state before provider I/O and treat it as the result.** Rejected because intention is not provider outcome and would create false lifecycle truth.
3. **Use process-local timestamps/counters after the provider call.** Rejected because they are not a durable cross-process ordering authority and cannot fail before external effects.
4. **Reserve a positive database-owned observation order before provider I/O, then persist a validated provider snapshot after success.** Chosen for `DurableBatchAPIClient`.

## Decision

For durable create, status-poll, and cancellation operations, `DurableBatchAPIClient` validates the endpoint/resource identity and obtains a positive database-owned **observation order** before the provider call. Reservation failure prevents provider I/O.

After a provider operation succeeds, the client revalidates the provider batch identity and bounded optional file/status/metadata fields before invoking the lifecycle recorder. Protected main persists the projection in `llm_remote_batch_jobs`, whose provider identity is the composite `(endpoint_alias, remote_batch_id)` on this baseline.

For cancellation, a provider response is persisted as cancellation lifecycle evidence only when the validated result reports accepted success. A persistence failure after provider success raises explicit bounded recovery information that identifies the operation, persistence phase, trusted endpoint/batch identity where available, observation order, and bounded error type.

## Consequences and non-goals

- The durable client can order observations across processes using PostgreSQL rather than event-loop timing.
- An unavailable ordering store fails before the external lifecycle call, preferring no effect over an untrackable effect when the package is asked to own persistence.
- Provider-success/persistence-failure remains possible and is surfaced as a first-class reconciliation case.
- This design does not provide a distributed transaction or distributed exactly-once delivery across PostgreSQL and the provider.
- It does not authenticate tenant/user identity; protected-main lifecycle state is not tenant-qualified.
- It does not make provider metadata authoritative merely because it was persisted.

## Failure and recovery

Reservation failure produces a bounded `GatewayError` before provider I/O. After provider success, identity/shape validation or recorder failure produces a persistence-phase reconciliation error without retrying the side-effecting provider operation.

Operators or embedding hosts recover by reconciling the trusted endpoint/batch identity and observation order against provider state and the current `llm_remote_batch_jobs` projection. A later valid observation may advance the projection according to database ordering semantics. Recovery tooling must not use untrusted provider body text as authority.

## Security, privacy, and governance impact

The durable projection stores provider identifiers, statuses, timestamps/counters, optional file identifiers, and normalized metadata subject to the implementation's bounds. Provider-controlled IDs/metadata are validated or normalized before persistence. Diagnostics retain bounded trusted identifiers and error classes rather than arbitrary provider bodies.

Trusted tenant selection is not provided by this protected-main decision. ACTIVE-PR #53 adds host-selected `tenant_scope` and PostgreSQL RLS; its review/integration must supersede or extend this ADR's key/authorization description when it becomes protected-main authority.

## Compatibility and migration

Hosts may continue to use `BatchAPIClient` when they own lifecycle persistence; `DurableBatchAPIClient` is the package-owned durable composition. The `llm_remote_batch_jobs` schema and recorder/reserver seams are compatibility surfaces for durable operation.

A future tenant-qualified key, new lifecycle event store, or different ordering primitive requires migration/rollback treatment and explicit compatibility guidance. Old observation evidence must not be silently re-parented or reordered without a reviewed migration contract.

## Verification and acceptance

Acceptance requires durable-client tests proving reservation-before-I/O, positive/non-boolean order validation, provider identity matching, create/poll/accepted-cancel persistence, failure-phase evidence, stale-order/concurrency behavior, schema uniqueness/state normalization, and no automatic replay of the side-effecting provider operation after persistence failure. Supported-version CI/security gates must pass on the source that changes this boundary.

## Rollback and supersession

A faulty lifecycle change may revert to the last protected durable-client/schema behavior if durable rows remain interpretable and no provider effects are falsified. This ADR is superseded only by a decision that names the new ordering/persistence authority, defines provider-success/local-failure reconciliation, migration and rollback, authorization/tenant ownership, concurrency semantics, and acceptance evidence.