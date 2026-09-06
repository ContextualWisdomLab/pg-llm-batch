# ADR 0032: Lifecycle Outbox DML Delegation Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox application role is intentionally limited to tenant-qualified `SELECT` and `INSERT`. ADR 0031 already rejects owner authority, `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` across the effective/session-selectable/administerable role closure.

The first delegation gap was direct PostgreSQL object privilege delegation. A principal holding `SELECT` or `INSERT` with `GRANT OPTION` can grant that object privilege onward to another role. The second, distinct mechanism is role-membership administration: a session identity holding `ADMIN OPTION` over a role that itself carries ordinary outbox `SELECT` or `INSERT` can grant that DML-bearing role to another principal even when the table privileges themselves are non-grantable.

Neither mechanism is described as an automatic RLS bypass. An ordinary delegated principal remains subject to PostgreSQL row-security rules. The defect is authorization delegation itself: the tenant application identity can manufacture additional outbox readers or writers, while principal provisioning and privilege delegation belong to the operator/authorization bounded context.

PostgreSQL exposes direct grant-option state through access-privilege inquiry functions. `WITH GRANT OPTION` can be appended to privileges checked by `has_table_privilege`, `has_any_column_privilege`, and related functions. PostgreSQL role membership separately exposes `ADMIN OPTION`; `pg_has_role(..., 'MEMBER WITH ADMIN OPTION')` tests that authority. The runtime guard therefore has to evaluate both object-level delegation and DML-bearing membership delegation.

## Decision

`_require_rls_application_role()` rejects any role in the existing effective/session-selectable/administerable closure that has either:

- `SELECT WITH GRANT OPTION` on any outbox column or the whole table; or
- `INSERT WITH GRANT OPTION` on any outbox column or the whole table.

It also rejects the authenticated `SESSION_USER` when that identity has membership `ADMIN OPTION` over a role whose effective privileges include outbox `SELECT` or `INSERT`. This second check is deliberately scoped to DML-bearing roles: unrelated administrable role memberships are not rejected merely because `ADMIN OPTION` exists.

The direct checks use schema-qualified `pg_catalog.has_any_column_privilege` against the already-resolved canonical outbox relation. The membership check combines schema-qualified `pg_catalog.pg_has_role(..., 'MEMBER WITH ADMIN OPTION')` with `has_any_column_privilege(..., 'SELECT'|'INSERT')` for the administered role. Both remain inside the existing single catalog round trip. Ordinary non-grantable `SELECT` and `INSERT` remain the supported application DML contract.

The package does not silently revoke object grant options or role membership administration. Operator/migration authority remains responsible for ACL and membership repair. Runtime admission only proves that the live connection authority is inside the package boundary before tenant binding or outbox data SQL.

## Alternatives considered

### Permit delegation because RLS still applies

Rejected. RLS controls row visibility and mutation for a principal; it does not make authorization delegation part of the application domain. The runtime has no product need to grant outbox privileges or DML-bearing memberships to other principals.

### Check only table-level grant options

Rejected. PostgreSQL permits column-level `SELECT` and `INSERT` grants. `has_any_column_privilege` covers both table and column forms and therefore avoids a silent object-delegation gap.

### Check only direct `WITH GRANT OPTION`

Rejected. A runtime login can hold no grantable table ACL at all and still redistribute outbox DML by administering membership in a role that already carries ordinary `SELECT` or `INSERT`. That authorization path is materially equivalent from the application/runtime boundary's perspective.

### Reject every membership `ADMIN OPTION`

Rejected as over-broad. The runtime admission query already observes the session-administerable closure, but administration of a role with no outbox DML does not by itself redistribute this bounded context's data privileges. The causal rule rejects `ADMIN OPTION` only when the administered role can use outbox `SELECT` or `INSERT`.

### Parse ACL or membership catalogs directly

Rejected. PostgreSQL already provides access/role inquiry functions that account for effective privilege and membership semantics. Reimplementing ACL or membership traversal would be more brittle and easier to diverge from the server version actually enforcing authorization.

### Revoke delegation authority automatically at runtime

Rejected. Runtime code does not own database authorization policy. Silent ACL or membership mutation would cross the application/operator bounded-context boundary and could invalidate independently managed access-control evidence.

## Verification lineage

Direct object-delegation lineage:

- static RED `c9dd5189488d6f5acfdfe1d5919e88dd593c3398` requires both direct grant-option predicates in the live role-authority query;
- PostgreSQL RED specimen `4f890a3da639bea9ef7444265dcc670d9a914791` creates an otherwise-minimal runtime login with outbox `SELECT, INSERT WITH GRANT OPTION` and requires package admission to fail closed;
- executable refinement `e50674cc534ea402b99f38f4c3319bddb93e2d52` gives the delegated role explicit schema usage, grants `SELECT` from the runtime identity, and requires the recipient to execute a real outbox read;
- CI wiring `8a51ec8a96e1e47f659fc7235f5d118686d5a1c9` places that specimen in the PostgreSQL/container acceptance lane;
- causal production repair `146e521a439c038e0b418a7c93c114140ad7fc1f` rejects table- or column-level `SELECT`/`INSERT` grant options anywhere in the existing role closure.

Role-membership delegation lineage:

- static/realistic RED `2131547f79f315008a711bfb5de2db0a2d69b587` requires the live query to reject `SESSION_USER` membership `ADMIN OPTION` over a DML-bearing role, creates an ordinary non-grantable `SELECT, INSERT` group role, delegates that group through `ADMIN OPTION` to a second login, proves the recipient can execute a real outbox read, and wires the specimen into the PostgreSQL/container lane;
- causal production repair `2cb5af9f4a4af54c0cbbba7949aefae4fbff5c4f` rejects that indirect delegation path by combining the membership-admin check with effective outbox `SELECT`/`INSERT` privilege checks for the administered role.

Exact-head hosted GREEN is required before this ADR can become Accepted. The executable membership specimen remains evidence design until the exact repaired final head actually runs in the hosted PostgreSQL lane.

## Consequences

The runtime identity may use only the DML it needs and may not redistribute that DML either directly through object grant options or indirectly through administration of a DML-bearing role. Security review and SOC 2/CSAP evidence can therefore treat outbox privilege delegation as operator-owned authorization change rather than application behavior. The added predicate remains in the existing single catalog round trip and does not add a second database query.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: 21.3. Role membership*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: GRANT*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: 9.27. System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html
