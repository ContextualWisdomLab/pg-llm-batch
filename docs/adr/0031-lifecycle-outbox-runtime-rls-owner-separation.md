# ADR 0031: Lifecycle Outbox Runtime RLS Owner Separation

- Status: Proposed
- Date: 2026-09-06

## Context

ADR 0002 requires shared lifecycle-outbox access to use PostgreSQL row-level
security with `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`, and it
already excludes `SUPERUSER` and `BYPASSRLS` application identities. Migration
0009 independently verifies the canonical relation and policy catalogs after
migration convergence.

The runtime admission check previously inspected only the effective
`CURRENT_USER` attributes in `pg_roles`. That is insufficient for the accepted
RLS boundary. PostgreSQL table owners normally bypass row security unless
`FORCE ROW LEVEL SECURITY` is active, and the table owner is also the authority
that can enable/disable row security or alter the policy boundary. A role may
therefore be `NOSUPERUSER NOBYPASSRLS` while still owning the lifecycle outbox or
holding role privileges that make the owner authority immediately usable,
selectable with `SET ROLE`, or self-grantable through role administration. Such
an identity is not separated application authority.

Migration-time verification alone also does not prove that `relrowsecurity` and
`relforcerowsecurity` remain enabled when a later runtime operation begins.

## Constraints

- Keep the caller-owned transaction seam and transaction-local tenant GUC.
- Do not parse DSN usernames as authorization evidence; `SET ROLE` changes the
  effective permission identity.
- Do not rerun migration 0009 for every read/write. That migration is an
  installer/final-admission verifier and performs substantially more catalog
  work than the hot runtime seam needs.
- Do not make an application role a schema owner merely to simplify deployment.
- Preserve the current fake-cursor contract and avoid an additional database
  round trip when the existing effective-role query can carry the extra proof.
- Do not reject inert role-membership edges merely because they exist. PostgreSQL
  16+ separates membership from `USAGE`/inheritance, `SET`, and role-admin
  authority, so the runtime check must follow exercisable owner authority rather
  than treating every `MEMBER` result as equivalent.

## Decision

Expand `_require_rls_application_role()` so its single catalog query joins the
canonical outbox relation and returns a combined fail-closed authority verdict.
Runtime access is admitted only when all of the following are simultaneously
true:

- effective `CURRENT_USER` is not superuser;
- effective `CURRENT_USER` does not have `BYPASSRLS`;
- `public.llm_context_lifecycle_outbox` currently has row security enabled;
- the relation currently has forced row security enabled;
- effective `CURRENT_USER` is not itself the relation owner;
- owner-role privileges are not immediately available to `CURRENT_USER`
  (`pg_has_role(..., 'USAGE') = false`);
- `CURRENT_USER` cannot select the owner with `SET ROLE`
  (`pg_has_role(..., 'SET') = false`); and
- `CURRENT_USER` lacks owner-role admin authority that could grant such access
  (`pg_has_role(..., 'MEMBER WITH ADMIN OPTION') = false`).

PostgreSQL 16 and 18 define `MEMBER` as direct or indirect membership without
regard to the privileges that membership actually confers, while `USAGE` and
`SET` distinguish immediately usable privileges from the ability to select a
role. PostgreSQL 16 also documents that a membership granted with
`INHERIT FALSE, SET FALSE` cannot exercise the target role's privileges either
implicitly or through `SET ROLE`. The causal repair therefore does not reject
membership that has no owner privilege path. Exact owner identity remains an
explicit OID comparison.

The relation is resolved through schema-qualified `pg_catalog.to_regclass`, so a
missing canonical relation produces no admissible row rather than falling back
to caller `search_path`.

Any missing, malformed, owner-capable, RLS-disabled, RLS-unforced, superuser, or
`BYPASSRLS` result raises the same content-free `ConfigError` before tenant GUC
binding or outbox data SQL.

This runtime guard complements rather than replaces migration 0009. Full policy,
CHECK, default, trigger/rule, index, relation-storage, and replay-arbiter
semantics remain installer/final-admission authority. Privileged operator DDL
racing after a successful runtime catalog read remains an administrative
boundary; application identities admitted here cannot themselves exercise the
outbox owner role through the checked effective-role authority paths.

## Alternatives considered

### Keep the `NOSUPERUSER NOBYPASSRLS` check only

Rejected. It admits a normal role that owns the outbox or can exercise its owning
role, even though PostgreSQL assigns RLS-control authority to the owner.

### Reject only exact `relowner = CURRENT_USER`

Rejected. PostgreSQL role privileges can make an owning role immediately usable,
selectable, or administratively self-grantable without `CURRENT_USER` itself
being the exact owner OID.

### Reject every direct or indirect `MEMBER` edge

Rejected after review. PostgreSQL 16+ can retain a membership while both
inheritance/usage and `SET` are disabled. Membership alone therefore overstates
the authority that can affect this runtime boundary. The final repair checks
exact ownership plus `USAGE`, `SET`, and membership-with-admin-option instead.

### Rerun migration 0009 on every runtime access

Rejected. It mixes installer convergence/final-admission work into a hot data
path and would repeat much broader catalog verification than is necessary to
establish application-role separation.

### Trust deployment documentation and never re-read relation RLS flags

Rejected. Post-migration restore or operator DDL can change relation-level RLS
flags while the application process remains alive. The existing role query can
carry the live relation flags without adding a second runtime round trip.

## Verification and promotion

TDD lineage for this decision:

- RED `f60522ca0ba33733110cdef0d46736e0d9e6edf7` requires live relation RLS and
  owner-separation evidence in the runtime admission query;
- executable PostgreSQL RED `ac8e780a751d2233f54b6e441081de8ecc85860d`
  transfers outbox ownership to a normal `NOSUPERUSER NOBYPASSRLS` role and
  proves that owner authority can disable `FORCE ROW LEVEL SECURITY` and expose
  both tenant rows;
- causal production repair `86411b4fb28e4429ebb966a87423ae810b91eb3b`
  extends the existing single runtime role query with live RLS flags and
  ownership authority;
- exact unit contract alignment `4201a09916cc79264548e463c6b867e12946fb13`
  preserves the two-boolean fake-cursor verdict while requiring the new catalog
  evidence in SQL;
- review repair `0ad858a9b9cbc3329f1ff0f1de2f65c7385d85e0` narrows the initial
  all-membership rejection to exact ownership plus exercisable `USAGE`, `SET`,
  and role-admin authority; `943bae891436d409c1eaa5987f68426954e1e9a2`
  pins those exact PostgreSQL privilege semantics in the unit contract;
- positive real-PostgreSQL control `ec51cc12f986a295dde2936971f5f47057eebcc5`
  grants the owner role with `INHERIT FALSE, SET FALSE` and default `ADMIN FALSE`,
  proves `MEMBER=true` while `USAGE=false`, `SET=false`, and admin-option=false,
  proves tenant visibility remains one row, and requires the production store to
  continue admitting that inert membership.

Keep this ADR Proposed until the exact repaired head executes the PostgreSQL
container specimen and repository quality gates successfully. Promotion to
Accepted requires that hosted evidence, not predecessor-head success.

## Consequences

Application deployments now require separation between the lifecycle outbox
owner authority and the runtime role, in addition to `NOSUPERUSER NOBYPASSRLS`.
An exact owner or a runtime role that can inherit, select, or administratively
acquire the owner role fails before tenant binding or durable-row access. An inert
membership with no such privilege path is not rejected solely for membership.

The hot path still performs one role/catalog round trip, as before; the query is
wider but does not add another network round trip. This decision does not claim a
new p95 latency result until the repository performance lane measures the exact
head.

## References

PostgreSQL Global Development Group. (2026a). *Row security policies*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026b). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026c). *pg_class*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-class.html

PostgreSQL Global Development Group. (2026d). *Role membership*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026e). *Role membership*. In *PostgreSQL
16 documentation*. https://www.postgresql.org/docs/16/role-membership.html

PostgreSQL Global Development Group. (2026f). *System information functions and
operators*. In *PostgreSQL 16 documentation*.
https://www.postgresql.org/docs/16/functions-info.html
