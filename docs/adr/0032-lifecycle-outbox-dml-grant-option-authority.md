# ADR 0032: Lifecycle Outbox Delegable and Executable Privilege Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox application role is intentionally limited to tenant-qualified `SELECT` and `INSERT`. ADR 0031 already rejects owner authority, `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` across the effective/session-selectable/administerable role closure.

Direct PostgreSQL object privilege delegation is one authorization path: a principal holding `SELECT` or `INSERT` with `GRANT OPTION` can grant that object privilege onward. Role-membership administration is another. A session identity holding `ADMIN OPTION` over a role can grant that role to other principals. If the administered role carries outbox DML itself, inherits it, or can reach a DML-bearing role through an all-`SET TRUE` membership path, the recipient can obtain the same outbox read/write authority even when every table privilege is non-grantable.

A third path is executable definer code. PostgreSQL `SECURITY DEFINER` functions execute with the privileges of their owner, and newly created functions grant `EXECUTE` to `PUBLIC` by default unless that privilege is explicitly revoked. A runtime identity can therefore remain an ordinary forced-RLS subject with no table grant option and still invoke user-schema code owned by a superuser, `BYPASSRLS` role, or the lifecycle-outbox table owner. The executable function may deliberately expose privileged behavior that the runtime role itself does not hold. Function security is therefore part of the live application-authority envelope, not merely a schema-design concern.

The DML-delegation cases are not described as automatic RLS bypasses: an ordinary delegated principal remains subject to row security. The `SECURITY DEFINER` case is different because the function executes as its owner; if that owner has RLS-bypass or outbox-owner authority, the function can execute with that elevated authority. The package does not attempt to prove that an arbitrary user-defined function body is harmless. Instead it requires ordinary lifecycle-outbox runtime identities not to have executable access to privileged `SECURITY DEFINER` code in user schemas.

## Decision

`_require_rls_application_role()` rejects any role in the existing effective/session-selectable/administerable closure that has either:

- `SELECT WITH GRANT OPTION` on any outbox column or the whole table; or
- `INSERT WITH GRANT OPTION` on any outbox column or the whole table.

It also rejects the authenticated `SESSION_USER` when that identity has membership `ADMIN OPTION` over a role that can confer outbox `SELECT` or `INSERT` after being granted onward. Admission recognizes two ways that administered role can confer DML:

- the administered role itself has effective outbox `SELECT` or `INSERT`, including inherited privilege; or
- the administered role can `SET ROLE` directly or indirectly to another role with outbox `SELECT` or `INSERT` through an all-`SET TRUE` path.

Finally, each selectable/administerable runtime role is rejected when all of the following are true:

- a non-system-schema routine is marked `SECURITY DEFINER`;
- that role has schema `USAGE` and routine `EXECUTE` authority; and
- the definer is a superuser, a `BYPASSRLS` role, or the canonical lifecycle-outbox table owner.

The executable-definer check uses `pg_catalog.pg_proc.prosecdef`, the function owner OID, schema identity, `has_schema_privilege(..., 'USAGE')`, and `has_function_privilege(..., 'EXECUTE')` inside the existing catalog admission round trip. PostgreSQL-owned `pg_*` schemas and `information_schema` are excluded from this user-schema guard so the package does not blanket-reject trusted server routines merely because PostgreSQL exposes a system `SECURITY DEFINER` object. The supported application boundary instead prohibits reachable privileged definer code in operator/application schemas. That is deliberately stronger than attempting to parse or allow-list arbitrary function bodies.

The package does not silently revoke object grant options, role membership administration, routine `EXECUTE`, or schema `USAGE`. Operator/migration authority remains responsible for ACL, membership, and routine reconciliation. Runtime admission only proves that the live connection authority is inside the package boundary before tenant binding or outbox data SQL.

## Alternatives considered

### Permit delegation because RLS still applies

Rejected. RLS controls row visibility and mutation for a principal; it does not make authorization delegation part of the application domain. The runtime has no product need to grant outbox privileges or DML-bearing memberships to other principals.

### Check only table-level grant options

Rejected. PostgreSQL permits column-level `SELECT` and `INSERT` grants. `has_any_column_privilege` covers both table and column forms and therefore avoids a silent object-delegation gap.

### Check only direct `WITH GRANT OPTION`

Rejected. A runtime login can hold no grantable table ACL at all and still redistribute outbox DML by administering membership in a role that already carries ordinary `SELECT` or `INSERT`.

### Check only the administered role's immediate/effective DML

Rejected. PostgreSQL allows `SET ROLE` to a directly or indirectly held role when every membership edge on the path has `SET TRUE`. An administered bridge role can therefore carry no inherited outbox DML itself and still confer a selectable DML role after that bridge is granted to another principal.

### Reject every membership `ADMIN OPTION`

Rejected as over-broad. Administration of a role with no effective outbox DML and no `SET` path to a DML-bearing role does not redistribute this bounded context's data privileges. The causal rule follows only the DML-bearing authority surface.

### Trust callable `SECURITY DEFINER` functions when the runtime role itself is ordinary

Rejected. PostgreSQL executes the function with its owner's privileges, so the caller's own `NOSUPERUSER`/`NOBYPASSRLS` attributes do not describe the authority used inside the function. The executable privilege edge must therefore be part of runtime admission.

### Parse or allow-list user-defined `SECURITY DEFINER` bodies

Rejected. Static SQL text is not a durable proof of effective behavior across procedural languages, dynamic SQL, dependencies, later routine replacement, and extension/operator calls. Treating an arbitrary privileged user-schema function as safe would create a second mutable authorization language inside this bounded context.

### Reject every `SECURITY DEFINER` routine in the database

Rejected as broader than the product boundary. PostgreSQL itself can expose system routines whose implementation and ownership are server authority. The application guard is scoped to executable privileged routines in non-system schemas, while operator policy remains free to impose a stricter database-wide rule.

### Parse ACL or membership catalogs manually

Rejected. PostgreSQL already provides access/role inquiry functions that account for effective privilege and membership semantics. Reimplementing ACL or membership traversal would be more brittle and easier to diverge from the server version actually enforcing authorization.

### Revoke delegation or routine authority automatically at runtime

Rejected. Runtime code does not own database authorization policy. Silent ACL, membership, or function privilege mutation would cross the application/operator bounded-context boundary and could invalidate independently managed access-control evidence.

## Verification lineage

Direct object-delegation lineage:

- static RED `c9dd5189488d6f5acfdfe1d5919e88dd593c3398` requires both direct grant-option predicates in the live role-authority query;
- PostgreSQL RED specimen `4f890a3da639bea9ef7444265dcc670d9a914791` creates an otherwise-minimal runtime login with outbox `SELECT, INSERT WITH GRANT OPTION` and requires package admission to fail closed;
- executable refinement `e50674cc534ea402b99f38f4c3319bddb93e2d52` gives the delegated role explicit schema usage, grants `SELECT` from the runtime identity, and requires the recipient to execute a real outbox read;
- CI wiring `8a51ec8a96e1e47f659fc7235f5d118686d5a1c9` places that specimen in the PostgreSQL/container acceptance lane;
- causal production repair `146e521a439c038e0b418a7c93c114140ad7fc1f` rejects table- or column-level `SELECT`/`INSERT` grant options anywhere in the existing role closure.

Role-membership delegation lineage:

- direct-admin RED `2131547f79f315008a711bfb5de2db0a2d69b587` adds a static contract and real PostgreSQL specimen where a runtime login holds `ADMIN OPTION` over a non-grantable DML role, grants it onward, and proves the recipient can execute a real outbox read;
- first causal repair `2cb5af9f4a4af54c0cbbba7949aefae4fbff5c4f` rejects membership administration over a role whose effective privileges already include outbox `SELECT` or `INSERT`;
- transitive RED `24a3e2265f29130c2ffe0679baa186a8288e2e52` adds a bridge whose own outbox DML is unavailable through inheritance but whose membership has `SET TRUE` to a DML leaf. The runtime has only `ADMIN OPTION` over that bridge, grants it to another login, and the recipient proves the all-`SET TRUE` chain by selecting the DML leaf and reading the outbox;
- causal production repair `8f45cc92da06fad1e0639c501f74759f41fd62bb` rejects membership administration when the administered role has effective outbox DML or can `SET` to any role that has it.

Executable-definer lineage:

- static RED `5df43f259739e1a1a80ec0723a702a4f6e0e2a26` requires live admission to inspect callable `SECURITY DEFINER` routines, their owners, and schema/function execution authority;
- executable PostgreSQL specimen `07d1181c903b7aa5c50b48e330d9d50d2cf42306` creates a superuser-owned `SECURITY DEFINER` function in `public`, proves a tenant-bound ordinary role can call it and observe both tenant rows, and requires package admission to fail closed before ordinary data SQL;
- the first hosted attempt of that specimen was blocked earlier in the container lane because PostgreSQL 16.15 rejects role names beginning with the reserved `pg_` prefix. Fixture-only repairs `c7f5b4dee8c8a592fae5b91ef1884c900003146a`, `43de9d87429dad24c3edf6cf519711f64c60b4df`, `98bb2c3b377dd12b6769634e8d7ac045af3dd03f`, `270f27e4f2c1c6273777544fe3df93a545d0aede`, `5ebac6e9990ca9c9f83b0fd9b129db38a0677e48`, and `29f02d77bfea9a23f9fa7484305d6495e43107fb` move the affected acceptance identities to the non-reserved `cwl_` namespace without changing production authorization semantics;
- causal production repair `df5a3bbbfbf9512ce1fab5bb13e6f15906f216ac` rejects executable privileged user-schema `SECURITY DEFINER` authority in the existing single catalog round trip;
- documentation-test convergence `02eb46b779235bd3ca6d66c42b7ace828588a874` also makes the operator-documentation contract assert the complete runtime-role attribute boundary rather than a stale adjacent substring.

Exact-head hosted GREEN is required before this ADR can become Accepted. Earlier or partially executed heads are evidence lineage only and are not transferred to the current head.

## Consequences

The runtime identity may use only the DML it needs and may not redistribute that DML directly, manufacture another DML-bearing membership, or invoke user-schema definer code whose owner reintroduces privileged outbox/RLS authority. Security review and SOC 2/CSAP evidence can therefore treat privilege delegation and privileged definer execution as operator-owned authorization change rather than application behavior. The added predicates remain in the existing catalog admission round trip; no second database query or silent ACL repair is introduced.

This deliberately narrows the supported deployment envelope. A database that intentionally exposes a superuser-, `BYPASSRLS`-, or outbox-owner-defined `SECURITY DEFINER` API to the same runtime principal must separate that API behind another connection/role or remove the runtime principal's executable path before using the lifecycle outbox. That operational inconvenience is preferable to claiming forced-RLS separation while the same identity can execute owner-level code.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: 21.3. Role membership*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: GRANT*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: 9.27. System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: SET ROLE*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026f). *PostgreSQL 18 documentation: CREATE FUNCTION*. https://www.postgresql.org/docs/18/sql-createfunction.html

PostgreSQL Global Development Group. (2026g). *PostgreSQL 18 documentation: 21.6. Function security*. https://www.postgresql.org/docs/18/perm-functions.html
