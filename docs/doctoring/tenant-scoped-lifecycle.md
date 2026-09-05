# Tenant-Scoped Durable Lifecycle Isolation

## Decision and trust boundary

Shared-table deployments use a trusted local `tenant_scope` as part of the
durable lifecycle identity. The embedding host selects this value only after
authentication and authorization. Provider metadata, remote identifiers,
endpoint aliases, request payloads, model output, and transport headers are not
tenant authorities.

`TenantDurableBatchAPIClient` validates the scope without trimming or coercion
before reservation, credential resolution, provider I/O, or database I/O.
Existing `DurableBatchAPIClient` consumers retain the original recorder seam
under the explicit `standalone` scope.

## Database enforcement

The durable identity is `(tenant_scope, endpoint_alias, remote_batch_id)`.
Every package lifecycle statement binds the validated scope using parameterized,
transaction-local `set_config('pg_llm_batch.tenant_scope', ..., true)` before
table access.

PostgreSQL row-level security uses matching `USING` and `WITH CHECK`
expressions. RLS is enabled and forced. Missing context therefore has no matching
row policy. PostgreSQL superusers and roles carrying `BYPASSRLS` bypass this
mechanism and cannot be used as production application identities.

Lifecycle-outbox migration policy predicates bind text equality with
`OPERATOR(pg_catalog.=)` and resolve the tenant setting through
`pg_catalog.current_setting`. PostgreSQL records the applicable command,
permissive/restrictive mode, roles, `USING`, and `WITH CHECK` expression trees
separately in `pg_policy`; the policy name is not sufficient security evidence.
Migration 0008 therefore accepts canonical v2 without DDL only when the stored
catalog row is all-command, permissive, exactly `PUBLIC`, and both expressions
decompile to the expected tenant equality. Same-name semantic drift is repaired.
An unknown policy name fails closed rather than being silently kept or deleted,
because an additional permissive policy could widen visible/writeable rows. The
resulting canonical v2 is verified again through `pg_policy` and `pg_get_expr`
before v1/legacy policy retirement. A semantically current v2 remains unchanged
on idempotent reapplication (PostgreSQL Global Development Group, 2026e, 2026f,
2026h).

Timestamp CHECK convergence also requires more than a name. PostgreSQL stores
constraint kind, validation status, and inheritance behavior separately in
`pg_constraint`. Migration 0008 accepts each canonical `valid_time` and
`system_time` constraint only when `contype = 'c'`, `convalidated` is true,
`connoinherit` is false, and `obj_description` returns the expected package
SHA-256 semantic stamp. A same-name wrong-kind, unvalidated, `NO INHERIT`, or
unstamped constraint is removed and rebuilt as the reviewed canonical CHECK,
then stamped before the legacy constraint is retired. A current stamped CHECK
is untouched (PostgreSQL Global Development Group, 2026i).

The semantic stamp is deliberately bounded evidence. PostgreSQL discards the
old constraint comment when a constraint is normally dropped, so an accidental
or ordinary operator same-name recreation cannot pass the migration guard
without also carrying the reviewed package stamp. A database administrator who
intentionally creates a different CHECK and copies that stamp can forge this
evidence; such an administrator already owns migration/catalog authority and is
outside the application isolation claim. The stamp is not advertised as a
cryptographic defense against hostile database administration.

The non-temporal lifecycle payload CHECKs also require post-create convergence.
PostgreSQL does not guarantee that an existing relation resembles the definition
supplied to `CREATE TABLE IF NOT EXISTS`; therefore the original CREATE-only
checks were insufficient authority for restored or manually repaired tables
(PostgreSQL Global Development Group, 2026k). Migration 0008 now converges one
validated inheritable aggregate
`ck_llm_context_lifecycle_outbox_payload_canonical_v1` covering trusted tenant
scope syntax, evidence/event identity grammar, every SHA-256 reference field,
and the closed truth-status vocabulary. Its package comment stamp is the SHA-256
of a canonical newline-delimited reviewed grammar and is reproduced by the
regression suite as
`29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a`.
A current stamped constraint is not rebuilt; a missing or stale same-name
constraint is recreated and PostgreSQL validates existing rows before migration
can succeed. As with the timestamp stamp, a privileged database administrator
can forge the comment and remains outside this application-level assurance.

Lifecycle-outbox replay convergence must also establish the concrete arbiter
used by runtime UPSERT. Migration 0008 checks the canonical
`uq_llm_context_lifecycle_outbox_tenant_evidence` row in `pg_constraint` and
accepts it only as a validated, nondeferrable UNIQUE constraint over exactly
`tenant_scope` then `evidence_id`. If the table pre-existed and the constraint is
missing, wrong-kind, deferrable, or attached to different columns, migration
adds or repairs the canonical constraint once. Existing duplicate identities
cause the UNIQUE addition to fail transactionally; migration does not delete or
merge durable evidence. PostgreSQL requires a usable unique index or
NOT DEFERRABLE constraint for `ON CONFLICT` arbitration (PostgreSQL Global
Development Group, 2026i, 2026j, 2026k).

The lifecycle outbox operational index has the same convergence requirement.
PostgreSQL explicitly states that `CREATE INDEX IF NOT EXISTS` only suppresses a
name collision and does not establish that the existing index resembles the
requested definition (PostgreSQL Global Development Group, 2026l). Migration
0008 therefore accepts
`idx_llm_context_lifecycle_outbox_tenant_created` only when `pg_index`,
`pg_class`, and `pg_am` prove a `public` B-tree that is valid, ready, live,
nonunique, has exactly two key/total attributes, has no expression or predicate,
and resolves its keys to `tenant_scope` followed by `created_at` (PostgreSQL
Global Development Group, 2026m). A same-name index on the outbox with the wrong
shape is rebuilt once. If the canonical name resolves to an unrelated relation,
migration raises a fixed collision error instead of deleting operator-owned
state. This is an operational performance/convergence guarantee, not evidence
that the buyer-path p95 target has been measured.

The lifecycle outbox also removes ambient PostgreSQL `search_path` from object
authority, but the runtime seam does so without changing caller transaction
state. Runtime tenant binding calls fully qualified `pg_catalog.set_config` and
runtime reads/writes address `public.llm_context_lifecycle_outbox` explicitly.
The earlier candidate that executed `SET LOCAL search_path` was superseded after
review showed that the changed path would remain active for unrelated SQL in the
caller-owned transaction.

Forward migration and rollback are installer-owned atomic statements, so their
`DO` blocks execute fully qualified
`pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true)`
before object resolution. PostgreSQL normally searches temporary schemas
specially when they are not explicitly named; putting `pg_temp` last prevents a
same-named temporary relation from preceding the reviewed application schema in
those statements (PostgreSQL Global Development Group, 2026g). This control
assumes `public` is the trusted package application schema; an operator must not
grant untrusted principals `CREATE` there.

`PostgresContextLifecycleOutboxStore` requires an explicit PostgreSQL DSN but
does not expose that exact value as a public store property. A DSN can contain
database credentials; the admitted value therefore remains package-internal
connection authority in the weak binding used by `load()` and `enqueue()`.
Tenant scope and its content-free digest stay observable because they are the
local authorization/evidence identities. This is an accidental-disclosure
control for normal logging and diagnostics, not an attempt to defend secrets
from arbitrary code executing inside the same Python process (Joint Task Force,
2020).

The setting itself is not a credential. PostgreSQL accepts custom two-part
configuration names, so a role that can execute arbitrary SQL can call
`set_config` with an arbitrary tenant scope. This design is a **trusted
application boundary** and is not a substitute for authentication,
authorization, SQL-injection prevention, restricted database privileges, or an
identity-to-tenant mapping layer. Generic SQL consoles and raw tenant-controlled
SQL must not use the application lifecycle role. Deployments that require direct
SQL should add a separately reviewed role mapping or security-definer interface.

## Migration and rollback

Existing rows are backfilled to `standalone`; no lifecycle row is deleted or
merged. The former endpoint/provider unique constraint is replaced by a
tenant-qualified constraint. The temporary owner-enforcement transition,
legacy-row backfill, constraint migration, `ENABLE ROW LEVEL SECURITY`, and
`FORCE ROW LEVEL SECURITY` restoration execute inside one anonymous PostgreSQL
block. A legacy installation therefore cannot commit a migrated table while RLS
is still disabled; policy recreation afterward remains default-deny until the
new policy exists.

For the Context Fabric lifecycle outbox, `CREATE TABLE IF NOT EXISTS` is followed
by catalog convergence for the payload grammar CHECK, runtime replay key, and
operational `(tenant_scope, created_at)` index. A pre-existing relation must
finish migration with the validated stamped canonical payload CHECK, a validated
NOT DEFERRABLE UNIQUE constraint on `(tenant_scope, evidence_id)`, and the exact
public B-tree operational index. Current canonical objects are left untouched.
Stale same-name objects are repaired only when the migration can prove they
belong to the outbox; invalid existing payload rows, duplicate replay identities,
and unrelated name collisions fail for operator reconciliation rather than being
silently changed.

Rollback to the former two-column key is unsafe until an operator proves that no
`(endpoint_alias, remote_batch_id)` pair appears in more than one tenant scope.
The lifecycle-outbox rollback additionally binds the reviewed search path before
`to_regclass`, emptiness inspection, and `DROP TABLE`, so ambient or temporary
same-name relations cannot redirect the destructive decision. The packaged
schema and Docker initialization schema remain byte-for-byte identical and must
support idempotent reapplication.

Enabling RLS is an operational compatibility change for direct SQL consumers.
Queries that do not bind an authorized transaction-local scope become
default-deny. Such consumers must migrate to the package helpers or a reviewed
database interface before deployment. Caller-owned outbox methods require a
real transaction for the transaction-local tenant GUC, but preserve the
caller's existing `search_path` rather than imposing one.

## Verification

Deterministic tests cover strict scope syntax, pre-effect validation,
tenant-recorder propagation, standalone compatibility, parameterized
transaction context, tenant-qualified conflict targets and reads, malformed
database rows, migration preservation, atomic RLS restoration, policy
default-deny behavior, exact schema mirroring, versioned policy convergence,
explicit `pg_catalog` operator/function binding, full canonical `pg_policy`
command/role/expression identity, unknown-policy fail-closed behavior,
post-create/post-repair policy verification, canonical timestamp CHECK
kind/validation/inheritance authority, reproducible payload grammar semantic
stamp, payload CHECK post-create convergence, same-name timestamp constraint
repair, runtime schema qualification without caller `search_path` mutation,
installer/rollback search-path binding, non-exposure of an admitted
credential-bearing outbox DSN, canonical replay-key
kind/deferrability/column identity, operational-index access method/state/key
identity, same-name wrong-key repair, unrelated-name-collision fail-closed
behavior, and documentation of the bounded assurance claim. Production
statement, branch, and public-docstring coverage remain at 100% only when
exact-head CI proves those gates.

Live PostgreSQL verification uses a `NOSUPERUSER NOBYPASSRLS` role, persists the
same provider identifier in two tenant scopes, and confirms each package-bound
scope can retrieve only its own lifecycle projection. This proves RLS mechanics
under the trusted package model; it does not claim protection after arbitrary
SQL execution is granted. Exact-head runtime verification must also exercise a
non-default caller `search_path`, confirm the canonical outbox relation is still
selected, confirm the caller's path is unchanged afterward, and execute
migration 0008 against stale-schema fixtures that omit, defer, or mis-key the
replay UNIQUE constraint, remove the legacy event-type plus canonical payload
checks, and replace the operational index with a same-name
`(created_at, tenant_scope)` index. PostgreSQL must reject the malformed payload
row and evaluate the final policy, payload/timestamp constraints, UPSERT arbiter,
and operational-index catalog conditions on that exact head.

## References

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Revision 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

MITRE. (2026). *CWE-89: Improper neutralization of special elements used in an
SQL command ('SQL injection')* (Version 4.20).
https://cwe.mitre.org/data/definitions/89.html

OWASP Foundation. (n.d.). *Multi-tenant security cheat sheet*. OWASP Cheat
Sheet Series. Retrieved August 5, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html

PostgreSQL Global Development Group. (2026a). *Customized options*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/runtime-config-custom.html

PostgreSQL Global Development Group. (2026b). *Row security policies*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026c). *SET*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-set.html

PostgreSQL Global Development Group. (2026d). *System administration
functions*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026e). *pg_policy*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026f). *CREATE POLICY*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026g). *Schemas*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/ddl-schemas.html

PostgreSQL Global Development Group. (2026h). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026i). *pg_constraint*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html

PostgreSQL Global Development Group. (2026j). *INSERT*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026k). *CREATE TABLE*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026l). *CREATE INDEX*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-createindex.html

PostgreSQL Global Development Group. (2026m). *pg_index*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-index.html
