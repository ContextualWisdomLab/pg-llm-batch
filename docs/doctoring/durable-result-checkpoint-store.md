# Durable result-checkpoint store assurance record

## Scope and claim boundary

This record covers tenant-qualified PostgreSQL persistence for immutable
`BatchResultCheckpoint` values. The implementation provides deterministic
compare-and-swap, idempotent repeat, caller-owned local transaction support,
forced row-level security, bounded conflict diagnostics, and a fail-closed
rollback migration.

It does **not** claim provider authentication, checkpoint signature or MAC,
full-stream immutability after the reproduced prefix, distributed exactly-once
delivery, or isolation for superusers, `BYPASSRLS` roles, generic tenant-controlled
SQL, or an incorrectly authorized tenant-to-scope mapping.

## Control rationale

### Concurrent writer control

PostgreSQL 18 documents that row-level `FOR UPDATE` locks block competing writers
and lockers until the current transaction ends. Existing-row advancement uses
that lock and exact `expected_previous` equality. Because a missing row cannot be
row-locked, initial creation additionally uses the compound unique key and
`ON CONFLICT ... DO NOTHING`, followed by locked reconciliation. This separates
identical idempotent races from conflicting first acknowledgements.

### Tenant isolation

PostgreSQL row security applies a default-deny posture when row-level security is
enabled and no applicable policy permits a row. The migration enables and forces
RLS, while package operations bind the trusted tenant with transaction-local
`set_config` and repeat the tenant key in each predicate. Production application
roles must be `NOSUPERUSER NOBYPASSRLS`.

NIST SP 800-53 Rev. 5 control families relevant to this slice include AC (Access
Control), AU (Audit and Accountability), CP (Contingency Planning), SC (System and
Communications Protection), and SI (System and Information Integrity). This
mapping is design evidence, not a certification or assertion that the package
alone satisfies an organization's full control implementation.

### Recovery and rollback

A checkpoint is stored only as the complete validated immutable value. A caller
may use `save_in_transaction()` so local PostgreSQL record effects and checkpoint
advancement commit or roll back together. The standalone `save()` method owns its
transaction for simpler deployments. External side effects still require a
transactional outbox, stable idempotency key, or explicit reconciliation.

A non-empty rollback guard cannot query through forced RLS with no tenant setting:
that context sees no rows and could falsely authorize destruction. The rollback
therefore executes as one atomic `DO` block, temporarily applies
`NO FORCE ROW LEVEL SECURITY`, and performs an owner-visible table-wide emptiness
check. If any acknowledgement exists, SQLSTATE 55000 aborts the transaction, so
the owner-enforcement relaxation is rolled back with the failed drop attempt. A
role lacking table-owner authority fails before it can relax RLS or drop the
table. Operators must export, reconcile, or explicitly remove checkpoint evidence
before schema rollback.

## Threat and failure matrix

| Threat or failure | Deterministic control | Residual boundary |
|---|---|---|
| Stale writer overwrites newer acknowledgement | `FOR UPDATE` plus exact `expected_previous` comparison | Administrative direct writes remain outside package guarantees |
| Two writers create the first checkpoint | Compound unique key, `ON CONFLICT`, locked reconciliation | Database outage still aborts the operation |
| Duplicate retry of the same acknowledgement | Exact checkpoint equality is idempotent | Duplicate external side effects require host idempotency |
| Regressive logical or physical position | Both `record_count` and `batch_line_count` must increase | A malicious database administrator can alter rows |
| Cross-tenant lookup or write | Forced RLS, transaction-local scope, tenant-qualified predicates | Superuser, `BYPASSRLS`, arbitrary SQL, and bad authorization mapping are excluded |
| Malformed database row | Reconstruct and revalidate `BatchResultCheckpoint`; invalid shape fails closed | Recovery requires operator repair |
| Forced RLS hides rows during rollback | Atomic owner-visible `NO FORCE ROW LEVEL SECURITY` check; non-empty evidence raises SQLSTATE 55000 and restores RLS by rollback | An authorized owner can still explicitly delete evidence before rerunning rollback |
| Provider suffix changes after checkpoint | Explicitly not attested by the prefix digest | Requires provider validator, authenticated digest, or full-stream manifest |
| Side effect and checkpoint split across systems | No false exactly-once claim | Requires outbox/idempotency/reconciliation at the host boundary |

## Verification evidence

Deterministic unit tests cover strict consumer and tenant validation, compound-key
SQL parameters, malformed rows, package-owned and caller-owned transaction paths,
idempotent repeats, stale and forked writers, logical and physical regressions,
identical and conflicting initial races, disappearing conflict rows, schema
installation, and 100% production statement and branch coverage.

Static migration tests require byte-identical package and container SQL, forced
RLS, tenant policy text, bounded digest and position constraints, descriptive
snake_case object names, no `BYPASSRLS`, and an owner-visible destructive rollback
guard ordered before both the evidence check and table drop. A live PostgreSQL
integration test exercises idempotent creation, exact advancement, load,
stale-writer rejection, and cleanup when `PG_LLM_BATCH_TEST_DSN` is set.

The bundled PostgreSQL image installs that same reviewed checkpoint migration as
`/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql`, after the cron
initialization script and without reusing another init destination. A permanent
container-installation regression requires both byte identity and this exact
ordered Dockerfile copy, so a fresh bundled PostgreSQL image cannot silently omit
the durable checkpoint schema.

Final merge evidence must be regenerated on the integrated exact head and base.
A successful stacked-branch run is development evidence only and cannot authorize
release, provenance, or reuse of an older artifact.

## APA 7th references

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

PostgreSQL Global Development Group. (n.d.). *PostgreSQL 18 documentation:
Explicit locking*. Retrieved August 6, 2026, from
https://www.postgresql.org/docs/18/explicit-locking.html

PostgreSQL Global Development Group. (n.d.). *PostgreSQL 18 documentation: Row
security policies*. Retrieved August 6, 2026, from
https://www.postgresql.org/docs/18/ddl-rowsecurity.html
