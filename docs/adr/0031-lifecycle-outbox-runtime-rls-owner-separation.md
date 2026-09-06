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

A second review of the same runtime boundary found that owner separation is
necessary but not sufficient. PostgreSQL row security applies to normal row
operations, not whole-table operations such as `TRUNCATE`, and the table
privilege model separately exposes `TRUNCATE`, `REFERENCES`, and `TRIGGER`.
`REFERENCES` can also be granted at column level. PostgreSQL explicitly warns
that foreign-key enforcement can be arranged to invoke arbitrary functions with
table-owner privileges and that installed triggers execute with the privileges
of users modifying the table. A normal `NOSUPERUSER NOBYPASSRLS` non-owner role
holding any of these authorities is therefore not a bounded lifecycle
application identity even when the live RLS flags and policy catalog are
canonical.

Migration-time verification alone also does not prove that `relrowsecurity` and
`relforcerowsecurity` remain enabled, or that dangerous application-role grants
have not been added, when a later runtime operation begins.

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
- Preserve the ordinary DML privileges needed by the store. In particular,
  `SELECT ... FOR UPDATE` requires `UPDATE` privilege on at least one column;
  rejecting all non-SELECT privileges would break the existing compare-and-swap
  path without improving the specific RLS-exempt/programming boundary.
- Detect column-level `REFERENCES`, not only a table-level grant.

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
  (`pg_has_role(..., 'SET') = false`);
- `CURRENT_USER` lacks owner-role admin authority that could grant such access
  (`pg_has_role(..., 'MEMBER WITH ADMIN OPTION') = false`);
- `CURRENT_USER` does not hold `TRUNCATE` on the outbox;
- `CURRENT_USER` does not hold table-level or column-level `REFERENCES` on the
  outbox, proved with `has_any_column_privilege(..., 'REFERENCES')`; and
- `CURRENT_USER` does not hold `TRIGGER` on the outbox.

PostgreSQL 16 and 18 define `MEMBER` as direct or indirect membership without
regard to the privileges that membership actually confers, while `USAGE` and
`SET` distinguish immediately usable privileges from the ability to select a
role. PostgreSQL 16 also documents that a membership granted with
`INHERIT FALSE, SET FALSE` cannot exercise the target role's privileges either
implicitly or through `SET ROLE`. The causal repair therefore does not reject
membership that has no owner privilege path. Exact owner identity remains an
explicit OID comparison.

The table-privilege checks are intentionally narrower than a blanket ACL ban.
`TRUNCATE` is destructive whole-table authority outside row-security filtering.
`REFERENCES` is checked through `has_any_column_privilege` because PostgreSQL can
grant it to specific columns as well as the full table. `TRIGGER` is executable
relation-programming authority. Ordinary `SELECT`, `INSERT`, and the minimum
`UPDATE` authority required for the package's `FOR UPDATE` path remain governed
by RLS and the existing package SQL contract.

The relation is resolved through schema-qualified `pg_catalog.to_regclass`, and
privilege inquiries use schema-qualified PostgreSQL system functions. A missing
canonical relation produces no admissible row rather than falling back to caller
`search_path`.

Any missing, malformed, owner-capable, RLS-disabled, RLS-unforced,
RLS-exempt/programming-privileged, superuser, or `BYPASSRLS` result raises the
same content-free `ConfigError` before tenant GUC binding or outbox data SQL.

This runtime guard complements rather than replaces migration 0009. Full policy,
CHECK, default, trigger/rule, index, relation-storage, and replay-arbiter
semantics remain installer/final-admission authority. Privileged operator DDL or
grant changes racing after a successful runtime catalog read remain an
administrative boundary; application identities admitted here cannot themselves
exercise the reviewed owner, truncate, reference, or trigger authority paths at
the time of admission.

## Alternatives considered

### Keep the `NOSUPERUSER NOBYPASSRLS` check only

Rejected. It admits a normal role that owns the outbox, can exercise its owning
role, or holds relation authority that sits outside or can program around the
row-security boundary.

### Reject only exact `relowner = CURRENT_USER`

Rejected. PostgreSQL role privileges can make an owning role immediately usable,
selectable, or administratively self-grantable without `CURRENT_USER` itself
being the exact owner OID. It also does not address independent `TRUNCATE`,
`REFERENCES`, or `TRIGGER` grants.

### Reject every direct or indirect `MEMBER` edge

Rejected after review. PostgreSQL 16+ can retain a membership while both
inheritance/usage and `SET` are disabled. Membership alone therefore overstates
the authority that can affect this runtime boundary. The final repair checks
exact ownership plus `USAGE`, `SET`, and membership-with-admin-option instead.

### Check only table-level `REFERENCES`

Rejected. PostgreSQL permits `REFERENCES` grants on specific columns. The
canonical replay key is itself a column pair, so a table-only privilege inquiry
would leave a real authority path unobserved. `has_any_column_privilege` covers
both table-wide and any column-level grant.

### Reject every table privilege except `SELECT` and `INSERT`

Rejected. The package intentionally uses `SELECT ... FOR UPDATE` in the
compare-and-swap path, and PostgreSQL requires `UPDATE` authority for that lock.
A blanket privilege allow-list would conflate RLS-subject DML with the distinct
whole-table/programming authorities addressed here and would break current
runtime behavior.

### Rerun migration 0009 on every runtime access

Rejected. It mixes installer convergence/final-admission work into a hot data
path and would repeat much broader catalog verification than is necessary to
establish application-role separation. It would still not replace a runtime
check of the current effective role's grants.

### Trust deployment documentation and never re-read relation RLS flags or grants

Rejected. Post-migration restore, GRANT, role change, or operator DDL can alter
runtime authority while the application process remains alive. The existing
role query can carry the live relation and privilege evidence without adding a
second runtime round trip.

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
  continue admitting that inert membership;
- privilege-boundary static RED `75693be1dff5e16ba4ccb02da546ad799342a9f2`
  requires the same runtime query to reject `TRUNCATE`, any table/column
  `REFERENCES`, and `TRIGGER` authority;
- executable PostgreSQL specimen `ef03358df4b1830a3c2bd7a5b96e2e686348fe30`
  proves a normal non-owner `TRUNCATE` role can remove both tenant rows inside a
  rollback transaction despite forced RLS, proves a column-level `REFERENCES`
  role can create a foreign key to the replay key, proves a `TRIGGER` role can
  attach a user trigger, and requires production admission to reject each role;
- causal production repair `86db8aa93e877186819e4698ac43bff6ba9be582`
  adds schema-qualified `has_table_privilege` / `has_any_column_privilege`
  checks to the existing one-round-trip authority verdict.

The new executable specimen is committed to the PostgreSQL/container lane but is
not claimed as hosted GREEN while the exact-head workflow remains queued. Keep
this ADR Proposed until the exact repaired head executes that specimen and the
repository quality gates successfully. Promotion to Accepted requires hosted
exact-head evidence, not predecessor-head success.

## Consequences

Application deployments now require separation between the lifecycle outbox
owner authority and the runtime role, in addition to `NOSUPERUSER NOBYPASSRLS`.
An exact owner or a runtime role that can inherit, select, or administratively
acquire the owner role fails before tenant binding or durable-row access. A role
holding outbox `TRUNCATE`, `TRIGGER`, or any table/column `REFERENCES` authority
also fails at the same boundary. An inert membership with no such privilege path
is not rejected solely for membership.

Deployments must therefore grant the runtime role only the RLS-subject DML
needed by the package and keep relation-maintenance/programming authority on a
separate operator identity. Existing deployments that bundled these grants into
the application role will fail closed until privileges are separated.

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

PostgreSQL Global Development Group. (2026g). *Privileges*. In *PostgreSQL 16
documentation*. https://www.postgresql.org/docs/16/ddl-priv.html

PostgreSQL Global Development Group. (2026h). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html