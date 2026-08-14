# Durable result-checkpoint store assurance record

## Scope and claim boundary

This record covers tenant-qualified PostgreSQL persistence for immutable
`BatchResultCheckpoint` values. The package provides deterministic compare-and-
swap, idempotent repeat, caller-owned local transaction support, forced row-level
security, bounded conflict diagnostics, bundled-image migration, and fail-closed
rollback.

It does **not** claim provider authentication, checkpoint signatures or MACs,
full-stream immutability after the reproduced prefix, distributed exactly-once
delivery, or isolation from PostgreSQL superusers, `BYPASSRLS` roles, arbitrary
tenant-controlled SQL, or an incorrectly authorized tenant-to-scope mapping.

## Control rationale

### Database target authority

Every package-owned durable-checkpoint surface requires an explicit nonblank
PostgreSQL DSN. `PostgresBatchResultCheckpointStore` validates its target during
construction, and `apply_result_checkpoint_schema()` applies the same validation
before Psycopg connects. Missing, empty, and whitespace-only values fail with a
bounded `ConfigError` before any connection attempt.

This prevents ambient libpq environment variables, service files, or local
defaults from silently selecting the checkpoint database when the application did
not supply reviewed authority. Caller-owned transaction methods do not reconnect;
they use the database authority represented by the supplied cursor.

### Concurrent writer control

Existing-row advancement uses `SELECT ... FOR UPDATE` plus exact
`expected_previous` equality. Because a missing row cannot be row-locked, initial
creation additionally uses the compound unique key and `ON CONFLICT ... DO
NOTHING RETURNING`, followed by locked reconciliation. Identical first writers
converge; conflicting first writers fail closed without overwrite.

### Tenant isolation

The migration enables and forces PostgreSQL row-level security. Store operations
bind the trusted tenant through transaction-local `set_config` and repeat tenant
scope in every key predicate. Production application roles must be
`NOSUPERUSER NOBYPASSRLS`. RLS is defense in depth, not authentication or a
substitute for the embedding host's authorization boundary.

### Recovery and rollback

A checkpoint is stored only as the complete validated immutable value. A caller
may use `save_in_transaction()` so local PostgreSQL record effects and checkpoint
advancement commit or roll back together. External side effects still require a
transactional outbox, stable idempotency key, or explicit reconciliation.

A non-empty rollback guard cannot rely on a query performed under forced RLS with
no tenant setting because that context can observe zero rows. The rollback runs
one atomic block, temporarily applies `NO FORCE ROW LEVEL SECURITY`, and performs
an owner-visible table-wide emptiness check. If any acknowledgement exists,
SQLSTATE 55000 aborts the transaction, restoring forced RLS with the rollback.
A role lacking owner authority cannot relax RLS or reach the destructive drop.

## Threat and failure matrix

| Threat or failure | Deterministic control | Residual boundary |
|---|---|---|
| Missing package-owned database target | Reject absent or blank DSN before Psycopg/libpq | Caller-owned cursors remain host authority |
| Stale writer overwrites newer acknowledgement | `FOR UPDATE` plus exact `expected_previous` | Administrative direct writes are outside package guarantees |
| Two writers create the first checkpoint | Compound unique key, `ON CONFLICT`, locked reconciliation | Database outage aborts the operation |
| Duplicate retry of the same acknowledgement | Exact equality is idempotent | Duplicate external side effects require host idempotency |
| Regressive logical or physical position | `record_count` and `batch_line_count` must increase | A database administrator can alter rows directly |
| Cross-tenant lookup or write | Forced RLS, transaction-local scope, tenant-qualified predicates | Superuser, `BYPASSRLS`, arbitrary SQL, and bad host authorization are excluded |
| Malformed database row | Reconstruct and revalidate `BatchResultCheckpoint` | Recovery requires operator repair |
| Forced RLS hides rows during rollback | Atomic owner-visible emptiness check; SQLSTATE 55000 on non-empty evidence | An authorized owner can explicitly delete evidence first |
| Provider suffix changes after checkpoint | Explicitly outside prefix evidence | Requires provider validator, authenticated digest, or manifest |
| Side effect and checkpoint split across systems | No false exactly-once claim | Requires outbox/idempotency/reconciliation |

## Verification evidence

Deterministic unit tests cover database-target, consumer, tenant, checkpoint, and
PostgreSQL-counter validation; compound-key SQL parameters; malformed rows;
package-owned and caller-owned transaction paths; idempotent repeats; stale and
forked writers; logical and physical regressions; identical and conflicting first
writers; and bounded conflict diagnostics.

Static migration tests require byte-identical package and container SQL, forced
RLS, tenant policy text, bounded digest and position constraints, descriptive
snake_case object names, no `BYPASSRLS`, and an owner-visible rollback guard.
The deployable image installs that same checkpoint migration as
`/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql` after its existing
initialization steps.

The permanent PostgreSQL container smoke verifies the table is actually present
in a fresh image, RLS and FORCE RLS are enabled, missing/cross-tenant access fails
closed for a non-superuser role, same-tenant access succeeds, empty rollback
drops the table, and non-empty rollback aborts while preserving forced RLS.

The same smoke runs the installed component image against the live PostgreSQL
container and proves simultaneous identical first writers converge, conflicting
first writers produce one success plus one bounded conflict, exact CAS advances,
stale writers cannot overwrite durable state, and caller-owned business effects
commit or roll back atomically with `save_in_transaction()`.

Final merge evidence must be regenerated on one unchanged exact head and live
base. Predecessor, queued, synthetic, status-only, or stale evidence does not
authorize integration or release.

## Operational recovery

For package-owned connections, correct missing target authority by supplying the
intended nonblank DSN through reviewed configuration. Do not recover availability
by allowing ambient libpq target selection. A valid explicit DSN can still fail
to connect because of network, TLS, authentication, or database availability;
those driver failures remain operator evidence and are not rewritten as target-
authority errors.

For checkpoint conflicts, stop automatic advancement and reconcile the durable
row with the exact provider prefix and the consumer's local effects. Do not
last-writer-win over a stale or forked checkpoint. For destructive rollback,
export, reconcile, or intentionally remove acknowledgement evidence before an
authorized owner reruns the rollback migration.

## References

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation:
Explicit locking*. https://www.postgresql.org/docs/18/explicit-locking.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Row
security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html
