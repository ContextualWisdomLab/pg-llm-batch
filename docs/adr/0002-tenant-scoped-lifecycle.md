# ADR 0002: Tenant-Scoped Durable Lifecycle State

- Status: Accepted
- Date: 2026-08-05

## Context

Provider batch identifiers are not globally unique across customer tenants. A
lifecycle table keyed only by endpoint alias and provider identifier cannot
provide a defensible shared-table identity. Provider metadata is untrusted data
and cannot establish tenant authority.

The package also needs to remain independently operable for existing
single-tenant consumers while providing a consistent integration boundary for
CWL services such as `naruon` and `contextual-orchestrator`.

PostgreSQL resolves unqualified relation, type, function, and operator names
through `search_path`; temporary schemas also have special precedence when they
are not explicitly placed. A tenant/RLS persistence boundary must therefore not
inherit caller-controlled name resolution for its runtime relation access,
installation DDL, or destructive rollback (PostgreSQL Global Development Group,
2026c).

PostgreSQL constraint names and comments are metadata, not complete executable
constraint authority. `pg_constraint` records constraint kind, validation state,
inheritance behavior, and the parsed expression tree separately. A restore or
manual DDL sequence can therefore recreate a same-name CHECK with different
semantics and copy an expected package comment. Migration convergence must
verify the installed predicate as well as its version/traceability metadata.
`pg_get_expr` reconstructs an expression from PostgreSQL's internal catalog
representation, so the running server can provide its own canonical decompiled
form rather than the migration hard-coding version-sensitive parser output
(PostgreSQL Global Development Group, 2026d, 2026e).

The lifecycle-outbox runtime also depends on PostgreSQL unique-index inference:
`enqueue_in_transaction()` uses `ON CONFLICT (tenant_scope, evidence_id) DO
NOTHING` as its durable replay boundary. `CREATE TABLE IF NOT EXISTS` does not
converge constraints on an already-existing relation, and PostgreSQL does not
accept a deferrable unique constraint as an `ON CONFLICT` arbiter. Migration
success must therefore establish the usable replay arbiter explicitly rather
than deferring that failure to the first enqueue (PostgreSQL Global Development
Group, 2026f, 2026g).

## Decision

Shared-table deployments must provide a trusted local `tenant_scope` selected
after host authentication and authorization. The lifecycle business key is
`(tenant_scope, endpoint_alias, remote_batch_id)`. Package reads and writes bind
the validated scope transaction-locally, and PostgreSQL row-level security is
enabled and forced.

The custom PostgreSQL setting is not a credential. This decision assumes a
trusted application boundary that prevents untrusted arbitrary SQL and maps an
authorized identity to the tenant scope. A role able to execute arbitrary SQL
can call `set_config` with an arbitrary tenant scope; therefore RLS is not a
substitute for authentication, authorization, SQL-injection prevention, or
restricted database privileges.

The existing `DurableBatchAPIClient` remains source compatible under the
explicit `standalone` scope. Shared deployments use
`TenantDurableBatchAPIClient` and its tenant-qualified recorder seam. Direct SQL
consumers must migrate to package helpers or a separately reviewed
identity-binding database interface.

Legacy rows are backfilled to `standalone`. Owner enforcement may be relaxed
only inside the same atomic SQL statement that performs the backfill, enables
row-level security for legacy tables, and restores `FORCE ROW LEVEL SECURITY`.
Policy recreation follows under enabled and forced default-deny behavior.

Versioned lifecycle-outbox policies must bind their equality operator and
`current_setting` lookup explicitly to `pg_catalog`. PostgreSQL stores policy
command, permissive mode, role set, security qualification, and `WITH CHECK`
expression separately in `pg_policy`; a policy name alone is not authority.
Migration 0008 therefore accepts the existing
`...tenant_scope_canonical_v2` policy without DDL only when the catalog proves
`FOR ALL`, permissive, exact `PUBLIC` role scope and canonical `USING` plus
`WITH CHECK` expression trees. A same-name v2 with semantic drift is replaced.
Policy names outside v2 and the two known predecessor names fail the migration
instead of being silently retained or deleted. The resulting v2 catalog state
is verified again before canonical v1 and the legacy policy are retired. This
keeps ordinary reapplication lock-bounded without accepting name-only drift
(PostgreSQL Global Development Group, 2026a, 2026b, 2026d).

Versioned lifecycle-outbox payload and timestamp constraints use executable
catalog identity plus a review stamp. Migration 0008 creates a session-local
temporary probe table containing the reviewed payload, `valid_time`, and
`system_time` CHECK definitions. The running PostgreSQL server decompiles those
probe expressions through `pg_get_expr(conbin, conrelid, false)`; the probe is
then dropped before durable constraint repair. A canonical package CHECK is
accepted only when `pg_constraint` reports a validated, inheritable CHECK, its
parsed expression equals the corresponding same-runtime probe expression, and
its comment carries the expected SHA-256 review stamp. A same-name or
same-name/same-stamp predicate drift is replaced once and the resulting catalog
state is verified again. An already-current durable CHECK avoids replacement
DDL (PostgreSQL Global Development Group, 2026d, 2026e, 2026g).

The semantic stamp remains traceability and version evidence inside the trusted
migration-authority boundary; it is no longer sufficient admission authority.
The parsed predicate comparison detects a copied stamp attached to different
executable CHECK semantics. This still does not create a security boundary
against a database administrator who can replace both database objects and the
reviewed migration bytes.

Payload grammar uses the same versioned convergence model, with one additional
rule: only after `ck_llm_context_lifecycle_outbox_payload_canonical_v1` is
established and post-verified does migration retire exactly the ten known
package-owned predecessor CHECK names for tenant/event/evidence identifiers,
digests, and truth status. Leaving those predecessor checks in place would
preserve multiple package grammar authorities; a restored stricter predecessor
could reject values that canonical v1 intentionally accepts. Unknown CHECK names
are not deleted because the migration cannot prove their ownership or disposal
semantics. On a converged installation the predecessor names are already absent,
so ordinary reapplication does not repeat those `ALTER TABLE ... DROP
CONSTRAINT` operations (PostgreSQL Global Development Group, 2026e, 2026g).

Migration 0008 also converges the lifecycle-outbox replay arbiter after table
creation. The canonical `uq_llm_context_lifecycle_outbox_tenant_evidence` state
is accepted only when `pg_constraint` identifies a validated, nondeferrable
UNIQUE constraint whose constrained columns are exactly `tenant_scope` then
`evidence_id`. A same-name wrong-kind, deferrable, or wrong-column constraint is
replaced once; a missing constraint is added. Existing duplicate rows make the
UNIQUE addition fail transactionally rather than being deleted or rewritten.
A current canonical constraint remains untouched on reapplication
(PostgreSQL Global Development Group, 2026e, 2026f, 2026g).

Lifecycle-outbox runtime must protect its own object authority without rewriting
caller-owned transaction state. It therefore binds the tenant GUC through fully
qualified `pg_catalog.set_config(..., true)` and addresses the relation as
`public.llm_context_lifecycle_outbox`; it does not change caller `search_path`.
The earlier candidate that issued `SET LOCAL search_path` in the runtime seam was
superseded because the setting would persist through the remainder of the
caller's transaction and could alter unrelated domain SQL resolution.

Forward migration and rollback are installer-owned atomic statements, so their
`DO` blocks bind the reviewed order `pg_catalog, public, pg_temp` with fully
qualified `pg_catalog.set_config(..., true)` before object lookup or DDL.
Because PostgreSQL uses the first existing search-path schema as the current
schema for unqualified creation, migration 0008 explicitly creates
`public.llm_context_lifecycle_outbox` rather than relying on that lookup order.
The canonical probe is intentionally a `TEMPORARY TABLE` with no explicit schema
qualifier, because PostgreSQL assigns temporary tables to the session temporary
schema; later catalog lookup references it through `pg_temp`. Explicitly placing
`pg_temp` last prevents its implicit relation precedence for other unqualified
lookups. The `public` schema remains the package's application schema; granting
untrusted principals `CREATE` there remains outside this assurance and must be
prevented operationally.

## Consequences

Embedding hosts must derive tenant scope from a trusted identity boundary and
use application roles that are `NOSUPERUSER NOBYPASSRLS`. Provider, model, and
transport values cannot select scope. Generic tenant-controlled SQL must not use
the lifecycle application role.

The tenant-qualified key allows identical provider identifiers in separate
tenants without collision. A missing transaction-local scope is default-deny,
which intentionally changes direct SQL behavior for existing integrations.

Caller-owned lifecycle-outbox methods preserve the transaction's existing
`search_path`; composition with unrelated domain SQL therefore does not receive
a hidden name-resolution mutation from the outbox. They still require a real
transaction because the tenant GUC is intentionally bound with
`set_config(..., true)` for transaction-local RLS scope. Package-owned `load()`
and `enqueue()` satisfy that contract through normal psycopg connection
transactions; custom autocommit use is not a supported implementation of the
caller-owned transaction seam.

An unexpected lifecycle-outbox policy is now a migration finding, not an
extension point. Operators that intentionally need a different policy set must
make that a separate reviewed architecture decision rather than adding a
permissive policy beside the canonical tenant boundary. A same-name altered v2
is repaired only because v2 is package-owned canonical state.

A package-owned canonical payload or timestamp CHECK that fails executable
predicate identity is also a repair finding, even if its name and comment stamp
look current. Repair can require table validation and its associated lock/work
once for a stale installation. A current installation still creates and reads a
session-local canonical probe on reapplication, but avoids replacing or
revalidating the durable CHECK.

Known pre-canonical payload CHECKs are migration predecessors rather than
independent durable invariants after canonical payload v1 exists. They are
removed only after canonical v1 is installed or admitted and post-verified. This
can acquire table locks once on a stale installation, but it prevents a stricter
restored predecessor from silently overriding the reviewed current grammar and
is a no-op for already-converged stores. Unknown CHECKs remain operator
findings, not automatic deletion targets.

A pre-existing outbox relation without the canonical nondeferrable
`(tenant_scope, evidence_id)` uniqueness invariant is likewise a repair finding.
Migration may build the unique index once and will fail if duplicate durable
identities already exist. That failure is intentional: duplicate lifecycle
identity requires operator reconciliation and must not be hidden by migration
cleanup. Once converged, runtime UPSERT has the arbiter it assumes.

Rollback to the prior two-column key requires first proving that no
endpoint/provider pair exists in multiple tenants and supplying a replacement
authorization boundary. Packaged and deployable schemas must remain exact
mirrors, and schema reapplication must be idempotent.

## References

PostgreSQL Global Development Group. (2026a). *pg_policy*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026b). *CREATE POLICY*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026c). *Schemas*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/ddl-schemas.html

PostgreSQL Global Development Group. (2026d). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026e). *pg_constraint*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html

PostgreSQL Global Development Group. (2026f). *INSERT*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026g). *CREATE TABLE*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-createtable.html
