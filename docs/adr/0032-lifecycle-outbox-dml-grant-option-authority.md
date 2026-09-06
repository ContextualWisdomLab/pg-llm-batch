# ADR 0032: Lifecycle Outbox Delegable and Executable Privilege Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox application role is intentionally limited to tenant-qualified `SELECT` and `INSERT`. ADR 0031 already rejects owner authority, `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` across the effective/session-selectable/administerable role closure.

Direct PostgreSQL object privilege delegation is one authorization path: a principal holding `SELECT` or `INSERT` with `GRANT OPTION` can grant that object privilege onward. Role-membership administration is another. A session identity holding `ADMIN OPTION` over a role can grant that role to other principals. If the administered role carries outbox DML itself, inherits it, or can reach a DML-bearing role through an all-`SET TRUE` membership path, the recipient can obtain the same outbox read/write authority even when every table privilege is non-grantable.

A third path is executable definer code. PostgreSQL `SECURITY DEFINER` functions execute with the privileges of their owner, and newly created functions grant `EXECUTE` to `PUBLIC` by default unless that privilege is explicitly revoked. A runtime identity can therefore remain an ordinary forced-RLS subject with no table grant option and still invoke user-schema code owned by a principal carrying authority that the runtime role is forbidden to hold directly.

The first repair for this path rejected callable user-schema `SECURITY DEFINER` functions owned by a superuser, `BYPASSRLS` role, or the lifecycle-outbox table owner. That was necessary but incomplete. A distinct non-owner, non-superuser, non-`BYPASSRLS` definer can still hold forbidden relation authority such as `TRUNCATE`. PostgreSQL explicitly states that whole-table operations including `TRUNCATE` and `REFERENCES` are not subject to row security. A callable definer carrying those privileges can therefore cross the same isolation/append-only boundary even though neither caller nor function owner satisfies the earlier three high-level predicates. The same authority-envelope problem applies to definer-held owner membership, `SELECT`/`INSERT` grant options, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` privileges that the package already rejects on the runtime role itself.

Fresh review then found that callable definer authority is not limited to relation ACLs. A non-superuser function owner with PostgreSQL `CREATEROLE` can execute role-administration statements through `SECURITY DEFINER` even though the caller itself is `NOCREATEROLE`. PostgreSQL's CREATE FUNCTION documentation specifically warns security-definer functions that create roles to pin `createrole_self_grant`, and CREATE ROLE requires `CREATEROLE` or superuser authority. Role administration belongs to the operator boundary already excluded from the lifecycle-outbox runtime identity, so callable user-schema code must not reintroduce it indirectly.

A further review exposed the same omission for `REPLICATION`. PostgreSQL defines `REPLICATION` as a highly privileged cluster role attribute and permits superusers or roles with that attribute to create and drop replication slots through SQL-callable system administration functions. A runtime login can remain `NOREPLICATION` while invoking a callable user-schema `SECURITY DEFINER` function whose owner has `REPLICATION`; the function executes with the owner's privilege and can create a physical replication slot. This is not characterized as an RLS bypass. It is indirect cluster replication authority that has no place in the tenant-scoped append-only application bounded context.

The same delegation problem also exists when the definer owner itself is `NOCREATEROLE` and holds no forbidden relation privilege directly. PostgreSQL `ADMIN OPTION` is authority to grant membership in the administered role onward; it is independent of whether the administrator can inherit that role or `SET ROLE` to it. A callable `SECURITY DEFINER` can therefore grant an administered bridge role to its caller. After the function returns, the caller can use an all-`SET TRUE` membership chain from that bridge to a role carrying destructive or otherwise forbidden lifecycle-outbox authority. PostgreSQL prohibits `SET ROLE` inside a `SECURITY DEFINER` function, but that restriction does not close this path: the privileged function performs `GRANT`, and the caller selects the newly granted role after returning to invoker context.

The DML-delegation cases are not described as automatic RLS bypasses: an ordinary delegated principal remains subject to row security. The executable-definer case differs because the function executes as its owner. In particular, `TRUNCATE` and `REFERENCES` are outside RLS, while owner/superuser/`BYPASSRLS` authority can bypass or alter the row-security boundary. `CREATEROLE`, `REPLICATION`, and role-membership administration are treated separately as cluster authorization authorities, not as automatic RLS bypasses. The package does not attempt to prove that an arbitrary user-defined function body is harmless. Instead it requires ordinary lifecycle-outbox runtime identities not to have executable access to user-schema `SECURITY DEFINER` code whose owner can exercise or redistribute authority that the runtime bounded context explicitly forbids.

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
- the definer carries forbidden lifecycle-outbox or operator authority directly, or can redistribute/reach it through membership administration: superuser, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, exact table ownership, inherited/exercisable owner authority, table/column `SELECT WITH GRANT OPTION` or `INSERT WITH GRANT OPTION`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, `TRIGGER`, or `ADMIN OPTION` over a role that carries or can `SET ROLE` to the same forbidden authority envelope.

For executable-definer membership administration, the live catalog query treats an administered role as dangerous when the definer owner has `MEMBER WITH ADMIN OPTION` on it and the role either carries forbidden operator/relation authority itself or has an all-`SET TRUE` path to another role that does. This follows the authority that can be granted to the caller rather than assuming `INHERIT FALSE` or `SET FALSE` on the definer owner's own membership makes the grant harmless.

The executable-definer check uses `pg_catalog.pg_proc.prosecdef`, the function owner OID, `pg_roles` role attributes, schema identity, `has_schema_privilege(..., 'USAGE')`, `has_function_privilege(..., 'EXECUTE')`, `pg_has_role(..., 'MEMBER WITH ADMIN OPTION')`, `pg_has_role(..., 'SET')`, `pg_has_role(..., relowner, ...)`, and PostgreSQL's table/column privilege inquiry functions inside the existing catalog admission round trip. PostgreSQL-owned `pg_*` schemas and `information_schema` are excluded from this user-schema guard so the package does not blanket-reject trusted server routines merely because PostgreSQL exposes a system `SECURITY DEFINER` object. The supported application boundary instead prohibits reachable privileged definer code in operator/application schemas. That is deliberately stronger than attempting to parse or allow-list arbitrary function bodies.

The package does not silently revoke object grant options, role membership administration, routine `EXECUTE`, schema `USAGE`, function ownership, role attributes, or definer-owner relation privileges. Operator/migration authority remains responsible for ACL, membership, role-attribute, routine, and replication reconciliation. Runtime admission only proves that the live connection authority is inside the package boundary before tenant binding or outbox data SQL.

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

Rejected as over-broad. Administration of a role with no effective outbox/operator authority and no `SET` path to such authority does not redistribute this bounded context's privileges. The causal rule follows the authority-bearing membership surface.

### Trust callable `SECURITY DEFINER` functions when the runtime role itself is ordinary

Rejected. PostgreSQL executes the function with its owner's privileges, so the caller's own `NOSUPERUSER`/`NOBYPASSRLS` attributes and direct ACLs do not describe the authority used inside the function. The executable privilege edge must therefore be part of runtime admission.

### Reject only superuser, `BYPASSRLS`, or exact-owner definers

Rejected as incomplete. A separate ordinary definer role can hold `TRUNCATE`, `REFERENCES`, mutation/programming privileges, grant options, exercisable owner-role authority, `CREATEROLE`, `REPLICATION`, or `ADMIN OPTION` over a dangerous role without satisfying those three predicates. Runtime admission must compare executable definer authority against the bounded context's forbidden relation and operator-authority envelope.

### Ignore non-relation role attributes on a definer

Rejected. `CREATEROLE` is exercised through SQL executed with the definer owner's privileges and can create cluster roles even when the caller is `NOCREATEROLE`. `REPLICATION` likewise authorizes SQL-callable replication-slot management even when the caller is `NOREPLICATION`. The lifecycle application connection needs neither role administration nor replication operator authority, and moving those operations behind a callable function does not move them into the application bounded context.

### Ignore `REPLICATION` because the runtime connection itself is not a replication-mode connection

Rejected. The concrete risk is not a hidden replication-mode startup parameter. PostgreSQL exposes replication-slot management as SQL-callable administration functions, and a `SECURITY DEFINER` function runs with its owner's privileges. A `NOREPLICATION` caller can therefore exercise the definer owner's `REPLICATION` authority without reconnecting in replication mode.

### Treat `SET ROLE` being forbidden inside `SECURITY DEFINER` as sufficient

Rejected. The threat does not require the function to select the administered role. `ADMIN OPTION` permits the function owner to grant that role to another principal. The function can perform the grant under definer authority; once it returns, the caller can follow any all-`SET TRUE` membership path that was conferred. Therefore a direct or transitive administered authority edge remains executable even though `SET ROLE` itself is prohibited while the security-definer body is running.

### Inspect only the definer owner's direct `ADMIN OPTION` target

Rejected. An administered bridge can deliberately carry no inherited relation authority while retaining `SET TRUE` to another role that owns destructive, DML, ownership, or operator authority. A grant of the bridge reproduces that selectable path for the recipient, so admission must inspect the target's `SET`-reachable authority as well.

### Reject only definer-held `TRUNCATE`

Rejected as symptom-specific. `TRUNCATE` provides a clear destructive relation specimen, but fixing only that privilege would leave equivalent indirect paths for the other relation capabilities and cluster administration that the package already treats as incompatible with the least-authority runtime boundary.

### Parse or allow-list user-defined `SECURITY DEFINER` bodies

Rejected. Static SQL text is not a durable proof of effective behavior across procedural languages, dynamic SQL, dependencies, later routine replacement, and extension/operator calls. Treating an arbitrary privileged user-schema function as safe would create a second mutable authorization language inside this bounded context.

### Reject every `SECURITY DEFINER` routine in the database

Rejected as broader than the product boundary. PostgreSQL itself can expose system routines whose implementation and ownership are server authority. The application guard is scoped to executable privileged routines in non-system schemas, while operator policy remains free to impose a stricter database-wide rule.

### Parse ACL or membership catalogs manually

Rejected. PostgreSQL already provides access/role inquiry functions that account for effective privilege and membership semantics. Reimplementing ACL or membership traversal would be more brittle and easier to diverge from the server version actually enforcing authorization.

### Revoke delegation or routine authority automatically at runtime

Rejected. Runtime code does not own database authorization policy. Silent ACL, membership, function, role-attribute, replication, or relation-privilege mutation would cross the application/operator bounded-context boundary and could invalidate independently managed access-control evidence.

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
- first causal production repair `df5a3bbbfbf9512ce1fab5bb13e6f15906f216ac` rejects executable user-schema `SECURITY DEFINER` authority when the definer is superuser, `BYPASSRLS`, or exact table owner;
- documentation-test convergence `02eb46b779235bd3ca6d66c42b7ace828588a874` makes the operator-documentation contract assert the complete runtime-role attribute boundary rather than a stale adjacent substring;
- static extension RED `511ef1ec7ace1cee624495c3d8eaa495647f5ce5` requires callable definers to be checked for inherited owner authority, grant options, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER`, not only the three high-level owner/RLS predicates;
- executable PostgreSQL specimen `0a32e44ef29afb14d1247ce15d5e772e30fe16ed` adds an ordinary non-owner, non-superuser, non-`BYPASSRLS` definer carrying only outbox `TRUNCATE`, proves an ordinary runtime login can execute that function and empty the outbox, and requires package admission to reject the callable authority;
- causal production repair `d1b225635e63448652ca74a63255a955564e11b5` extends the existing single catalog round trip to compare executable definer owners against the forbidden outbox relation-authority envelope without mutating ACLs;
- static `CREATEROLE` RED `6ca1edf1e8405550235deb2a2809876bce373e13` requires the same callable-definer query to reject a definer owner with role-administration authority;
- causal production repair `9921f551d6a64770b93bd769ab599c2cdd1bae0d` adds `definer_role.rolcreaterole` to that existing catalog admission round trip;
- executable PostgreSQL specimen `554189734a8ef257ba9a496f984866f2fea03709` creates a non-superuser `CREATEROLE` function owner, proves an ordinary `NOCREATEROLE` runtime login can invoke its `SECURITY DEFINER` routine and create a cluster role, and then requires package admission to fail closed before tenant data SQL;
- static `REPLICATION` RED `d8f95092b08124063d636537831503710eefaf51` requires the callable-definer query to inspect `definer_role.rolreplication` rather than assuming the caller's `NOREPLICATION` attribute bounds executable authority;
- causal production repair `e2116cf9a87938cac67b41ba17dd4a4e09b5ec48` adds `definer_role.rolreplication` to the existing admission round trip;
- executable PostgreSQL specimen `c5c9761583ef91a34d6f3ca5fb1c7d86c935037a` creates a `NOLOGIN REPLICATION` function owner and ordinary `LOGIN NOREPLICATION` caller, proves the caller can invoke the owner's `SECURITY DEFINER` routine to create a physical replication slot, and then requires package admission to fail closed before tenant data SQL;
- CI wiring `439e22b0df22c43af6c5855779128642b9f2a7a4` places that replication-authority specimen in the PostgreSQL/container acceptance lane;
- static definer-administration RED `8ae6de147bc9b1746f25d4b29f6de43b6ed7d4a8` requires executable-definer admission to inspect the function owner's `ADMIN OPTION` targets and their `SET`-reachable authority rather than only the owner's direct attributes and ACLs;
- causal production repair `646fadfbefe6c93e9255face270594861695309e` extends the same catalog round trip with `definer_admin_role` and `definer_admin_set_role` authority probes while leaving ACL/membership repair operator-owned;
- executable PostgreSQL specimen `cba5f92a62f91c6aecee2c2c68f9f1cfcda25e6c` gives an otherwise ordinary definer owner `ADMIN OPTION` over an `INHERIT FALSE, SET FALSE` bridge, gives that bridge `SET TRUE` to a `TRUNCATE` role, proves the callable definer can grant the bridge to an ordinary runtime login and that the login can then traverse the `SET` chain and empty the outbox, revokes the newly delegated membership, and requires package admission to reject the still-callable latent authority;
- CI wiring `fb6c3bba7aad728290f0be27e9591888c0584cb6` places the definer-admin specimen in the PostgreSQL/container acceptance lane.

Exact-head hosted GREEN is required before this ADR can become Accepted. Earlier or partially executed heads are evidence lineage only and are not transferred to the current head.

## Consequences

The runtime identity may use only the DML it needs and may not redistribute that DML directly, manufacture another DML-bearing membership, invoke user-schema definer code whose owner reintroduces forbidden outbox relation authority, invoke such code carrying `CREATEROLE` or `REPLICATION`, or invoke such code whose owner can redistribute a role that directly or transitively exposes the forbidden authority envelope. Security review and SOC 2/CSAP evidence can therefore treat privilege delegation, privileged definer execution, role administration, and replication administration as operator-owned authorization change rather than application behavior. The added predicates remain in the existing catalog admission round trip; no second database query or silent ACL/role repair is introduced.

This deliberately narrows the supported deployment envelope. A database that intentionally exposes a user-schema `SECURITY DEFINER` API whose owner carries superuser, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, lifecycle-outbox ownership, owner-membership, grant-option, destructive/mutating, reference, trigger, or authority-bearing `ADMIN OPTION` to the same runtime principal must separate that API behind another connection/role or remove the runtime principal's executable path before using the lifecycle outbox. That operational inconvenience is preferable to claiming least-authority application separation while the same identity can execute privileged database administration, replication administration, relation code, or membership delegation.

The guard is authority-based rather than body-based. A privileged definer may be harmless today, but admitting it would make a later body replacement an application-isolation change without changing the runtime role itself. Conversely, ordinary `SECURITY DEFINER` functions whose owners do not carry or redistribute the forbidden authority remain outside this specific rejection predicate; operator policy may choose a stricter database-wide prohibition.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: 5.9. Row security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: 21.3. Role membership*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: GRANT*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: 9.27. System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026f). *PostgreSQL 18 documentation: SET ROLE*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026g). *PostgreSQL 18 documentation: CREATE FUNCTION*. https://www.postgresql.org/docs/18/sql-createfunction.html

PostgreSQL Global Development Group. (2026h). *PostgreSQL 18 documentation: 21.6. Function security*. https://www.postgresql.org/docs/18/perm-functions.html

PostgreSQL Global Development Group. (2026i). *PostgreSQL 18 documentation: TRUNCATE*. https://www.postgresql.org/docs/18/sql-truncate.html

PostgreSQL Global Development Group. (2026j). *PostgreSQL 18 documentation: CREATE ROLE*. https://www.postgresql.org/docs/18/sql-createrole.html

PostgreSQL Global Development Group. (2026k). *PostgreSQL 18 documentation: 21.2. Role attributes*. https://www.postgresql.org/docs/18/role-attributes.html

PostgreSQL Global Development Group. (2026l). *PostgreSQL 18 documentation: 9.28. System administration functions*. https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026m). *PostgreSQL 18 documentation: pg_roles*. https://www.postgresql.org/docs/18/view-pg-roles.html
