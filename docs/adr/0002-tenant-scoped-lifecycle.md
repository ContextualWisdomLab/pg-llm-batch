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

PostgreSQL constraint names are identifiers, not complete constraint authority.
`pg_constraint` records constraint kind, validation state, and inheritance
behavior separately; a same-name row can therefore fail to represent the
reviewed canonical CHECK. A normal drop/recreate also discards the package
comment attached to the old constraint. Migration convergence can use these
catalog properties plus a package-owned semantic stamp to detect ordinary
same-name drift without parsing PostgreSQL's internal expression tree
(PostgreSQL Global Development Group, 2026e).

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

Versioned lifecycle-outbox timestamp constraints use a package semantic identity
in addition to catalog state. Migration 0008 accepts
`ck_llm_context_lifecycle_outbox_valid_time_canonical_v1` or
`ck_llm_context_lifecycle_outbox_system_time_canonical_v1` as current only when
the matching `pg_constraint` row is a validated, inheritable CHECK and its
constraint comment carries the expected SHA-256 semantic stamp for the reviewed
CHECK source. If the canonical name has another kind, remains unvalidated, is
`NO INHERIT`, or lacks the expected stamp, migration drops that package-owned
same-name constraint and adds the reviewed canonical CHECK and stamp before
retiring the legacy timestamp constraint. A current stamped constraint remains
untouched on reapplication (PostgreSQL Global Development Group, 2026e).

The semantic stamp is an integrity/version identity inside the trusted
migration-authority boundary. It detects ordinary package-owned drop/recreate or
operator drift because the old constraint comment does not survive replacement.
It is not a security boundary against a database administrator who deliberately
creates a different CHECK and copies the package stamp; such an administrator
already controls migration/catalog authority and remains outside this assurance.

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
Explicitly placing `pg_temp` last prevents its implicit relation precedence. The
`public` schema remains the package's application schema; granting untrusted
principals `CREATE` there remains outside this assurance and must be prevented
operationally.

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

A same-name timestamp constraint without the validated inheritable CHECK
properties and expected package semantic stamp is also a repair finding. The
migration replaces that package-owned drift rather than accepting it or merely
dropping the legacy check. This may require table validation and its associated
lock/work once for a stale installation; a current installation avoids that
repeated DDL.

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
