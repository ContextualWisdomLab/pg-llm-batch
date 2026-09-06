# ADR 0032: Lifecycle Outbox Delegable and Executable Privilege Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox runtime is an application DML identity. Its normal database contract is tenant-qualified, forced-RLS `SELECT` and `INSERT`; database administration, role administration, replication, relation programming, destructive/mutating DML, and privilege delegation remain operator authority.

ADR 0031 already requires the effective/authenticated role closure to reject `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, outbox ownership or exercisable owner authority, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER`. That direct-role check is necessary but not sufficient because PostgreSQL exposes two further authorization paths.

First, object and role authority can be delegated. `SELECT WITH GRANT OPTION` and `INSERT WITH GRANT OPTION` let a principal create new outbox readers/writers. `ADMIN OPTION` on a role lets the administrator grant that role onward. An administered bridge role can itself carry no inherited outbox DML yet have an all-`SET TRUE` membership path to another role that does; once the bridge is granted, the recipient can select the downstream authority.

Second, callable `SECURITY DEFINER` code executes with its owner's privileges rather than its caller's. A caller that is an ordinary forced-RLS role can therefore exercise operator authority through a user-schema function owner. Real specimens in this repository establish three distinct executable cases: a non-owner definer with outbox `TRUNCATE`, a `CREATEROLE` definer that can create a cluster role, and a `REPLICATION` definer that can create a physical replication slot. Those are different mechanisms and are not collapsed into an RLS-bypass claim.

Fresh review exposed a further delegation case. The callable definer owner can itself be `NOCREATEROLE` and hold no forbidden outbox privilege directly, but hold membership `ADMIN OPTION` over a bridge role. PostgreSQL treats `ADMIN`, `INHERIT`, and `SET` as distinct membership options. The administrator may grant the administered role onward even when its own membership is `INHERIT FALSE, SET FALSE`. PostgreSQL also prohibits `SET ROLE` while a `SECURITY DEFINER` function is executing, but that restriction does not close this path: the function performs `GRANT` under the owner's authority, returns, and the caller can then use the newly granted role's all-`SET TRUE` path in invoker context.

`CREATEDB` needs one explicit distinction. Direct runtime identities remain `NOCREATEDB` under ADR 0031. A callable definer owner is not rejected merely for `CREATEDB`, because the product has not established an executable in-function `CREATE DATABASE` path and PostgreSQL prohibits `CREATE DATABASE` inside a transaction block. `CREATEDB` is nevertheless forbidden when it is authority that a callable definer owner can grant onward through membership administration, because the caller may exercise that newly granted role later outside the security-definer call. The implemented guard follows this distinction rather than over-claiming direct executable `CREATEDB` semantics.

## Decision

`_require_rls_application_role()` retains one fail-closed PostgreSQL catalog round trip before tenant binding or outbox data SQL and rejects the following authority.

### Direct object delegation

Every role in the existing effective/session-selectable/administerable runtime closure is rejected when it has:

- table- or column-level `SELECT WITH GRANT OPTION`; or
- table- or column-level `INSERT WITH GRANT OPTION`.

The package does not silently revoke those privileges.

### Authenticated-session role delegation

The authenticated `SESSION_USER` is rejected when it has `MEMBER WITH ADMIN OPTION` over a role that can confer outbox `SELECT` or `INSERT` after being granted onward. An administered role is authority-bearing when it either:

- has effective outbox `SELECT` or `INSERT`, including inherited privilege; or
- can `SET ROLE` directly or indirectly through an all-`SET TRUE` path to another role with that DML.

This follows what the authenticated identity can redistribute, not only what its current effective role can exercise.

### Callable `SECURITY DEFINER` authority

For each non-system-schema `SECURITY DEFINER` routine that a selectable/administerable runtime role can execute through schema `USAGE` plus routine `EXECUTE`, admission inspects the routine owner.

The direct definer-owner authority envelope rejects:

- `SUPERUSER`;
- `CREATEROLE`;
- `REPLICATION`;
- `BYPASSRLS`;
- exact outbox ownership or exercisable owner authority;
- outbox `SELECT WITH GRANT OPTION` or `INSERT WITH GRANT OPTION`;
- outbox `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, or `TRIGGER`.

The executable-definer membership-administration envelope additionally rejects a definer owner that has `MEMBER WITH ADMIN OPTION` over a role when that administered role either directly carries, or has an all-`SET TRUE` path to, forbidden runtime/operator authority. The target/reachable authority checked by the current implementation includes:

- `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, or `BYPASSRLS`;
- exact/exercisable outbox ownership;
- outbox `SELECT` or `INSERT`;
- outbox `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, or `TRIGGER`.

This target check intentionally uses ordinary `SELECT`/`INSERT` rather than only grant-option forms: after the definer grants the role to the caller, ordinary DML held by that role becomes usable authority. Likewise, `CREATEDB` is checked on an administered/reachable role because that authority can be granted to the caller for later invoker-context use even though direct callable-definer `CREATEDB` is not currently treated as an executable in-function capability.

The guard uses PostgreSQL's own role/privilege inquiry functions and catalogs, including `pg_proc.prosecdef`, function owner OIDs, `pg_roles` attributes, `has_schema_privilege`, `has_function_privilege`, `pg_has_role(..., 'MEMBER WITH ADMIN OPTION')`, `pg_has_role(..., 'SET')`, `has_table_privilege`, and `has_any_column_privilege`. PostgreSQL-owned `pg_*` schemas and `information_schema` remain outside this user-schema definer guard; operator policy may impose a stricter database-wide prohibition.

The package never auto-revokes ACLs, membership, role attributes, routine execution, schema usage, function ownership, or replication authority. Repair remains operator-owned.

## Alternatives considered

### Trust RLS because delegated readers/writers are still ordinary roles

Rejected. RLS controls row access; it does not make authorization delegation part of the application bounded context. The runtime has no product need to manufacture additional outbox principals.

### Check only table-level grant options

Rejected. PostgreSQL supports column-level `SELECT` and `INSERT` grants. `has_any_column_privilege(..., '... WITH GRANT OPTION')` covers both table and column forms without parsing ACL text.

### Check only the administered role's immediate DML

Rejected. An administered bridge may have no inherited DML and still have an all-`SET TRUE` path to a DML-bearing role. Granting the bridge reproduces that selectable path for the recipient.

### Reject every `ADMIN OPTION`

Rejected as broader than the causal boundary. Administration of a role with no relevant operator/outbox authority and no relevant `SET` path does not redistribute this bounded context's authority.

### Trust an ordinary caller when the privileged work is behind `SECURITY DEFINER`

Rejected. PostgreSQL executes the routine with its owner's privileges. Caller attributes therefore do not describe the authority used by the function.

### Reject only superuser, `BYPASSRLS`, or exact-owner definers

Rejected. Real specimens prove ordinary separate function owners can hold `TRUNCATE`, `CREATEROLE`, or `REPLICATION` without satisfying those three predicates.

### Treat `SET ROLE` being forbidden inside `SECURITY DEFINER` as sufficient

Rejected. The definer does not need to select the administered role. It can grant that role to the caller, return, and leave the caller with a selectable authority path.

### Inspect only the definer owner's immediate `ADMIN OPTION` target

Rejected. An administered bridge can be deliberately inert for inheritance while retaining `SET TRUE` to a downstream destructive/operator role.

### Reject direct callable-definer `CREATEDB` solely for symmetry

Rejected pending causal executable evidence. Direct runtime `CREATEDB` remains forbidden by ADR 0031, and an administered/reachable `CREATEDB` role remains forbidden here because it can be granted onward. The callable-definer owner predicate itself is not widened beyond the authority demonstrated executable within this boundary.

### Parse or allow-list user-defined function bodies

Rejected. SQL text is not durable behavioral authority across procedural languages, dynamic SQL, dependencies, routine replacement, and extensions. Authority is checked from the live executable privilege graph instead.

### Revoke unsafe authority automatically

Rejected. Runtime code does not own database authorization policy. Silent ACL or membership mutation would cross the application/operator boundary and invalidate independent access-control evidence.

## Verification lineage

### Direct object delegation

- static RED `c9dd5189488d6f5acfdfe1d5919e88dd593c3398`;
- PostgreSQL RED `4f890a3da639bea9ef7444265dcc670d9a914791`;
- executable delegation refinement `e50674cc534ea402b99f38f4c3319bddb93e2d52`;
- CI wiring `8a51ec8a96e1e47f659fc7235f5d118686d5a1c9`;
- causal repair `146e521a439c038e0b418a7c93c114140ad7fc1f`.

### Authenticated-session membership delegation

- direct-admin RED `2131547f79f315008a711bfb5de2db0a2d69b587`;
- first repair `2cb5af9f4a4af54c0cbbba7949aefae4fbff5c4f`;
- transitive `SET` RED `24a3e2265f29130c2ffe0679baa186a8288e2e52`;
- causal transitive repair `8f45cc92da06fad1e0639c501f74759f41fd62bb`.

### Callable-definer authority

- initial callable-definer static RED `5df43f259739e1a1a80ec0723a702a4f6e0e2a26` and superuser-owned PostgreSQL specimen `07d1181c903b7aa5c50b48e330d9d50d2cf42306`;
- first direct-definer repair `df5a3bbbfbf9512ce1fab5bb13e6f15906f216ac`;
- relation-authority extension RED `511ef1ec7ace1cee624495c3d8eaa495647f5ce5`, real `TRUNCATE` specimen `0a32e44ef29afb14d1247ce15d5e772e30fe16ed`, causal repair `d1b225635e63448652ca74a63255a955564e11b5`;
- callable `CREATEROLE` RED `6ca1edf1e8405550235deb2a2809876bce373e13`, repair `9921f551d6a64770b93bd769ab599c2cdd1bae0d`, real PostgreSQL specimen `554189734a8ef257ba9a496f984866f2fea03709`;
- callable `REPLICATION` RED `d8f95092b08124063d636537831503710eefaf51`, repair `e2116cf9a87938cac67b41ba17dd4a4e09b5ec48`, real PostgreSQL specimen `c5c9761583ef91a34d6f3ca5fb1c7d86c935037a`, CI wiring `439e22b0df22c43af6c5855779128642b9f2a7a4`;
- callable definer-owner membership-administration RED `8ae6de147bc9b1746f25d4b29f6de43b6ed7d4a8`;
- causal query repair `646fadfbefe6c93e9255face270594861695309e` followed by self-review SQL-grouping correction `988ed9b611bc442891e9769ae86a0caf63764ab3`;
- real PostgreSQL transitive delegation specimen `cba5f92a62f91c6aecee2c2c68f9f1cfcda25e6c`;
- PostgreSQL/container CI wiring `fb6c3bba7aad728290f0be27e9591888c0584cb6`.

The new admin-delegation specimen deliberately gives the definer owner no `CREATEROLE` and no direct destructive relation privilege. It grants an `INHERIT FALSE, SET FALSE` bridge that has `SET TRUE` to an outbox `TRUNCATE` role, proves the ordinary caller can traverse the newly granted role chain and empty the outbox, revokes the caller's materialized bridge membership, and then requires package admission to reject the still-callable latent authority. That separates the causal defect from both direct definer privileges and already-materialized caller authority.

Earlier heads, partial jobs, and superseded workflow runs are lineage only. ADR 0032 remains Proposed until one unchanged exact repaired head executes the static contracts, full unit/coverage gates, and all wired PostgreSQL/container specimens successfully.

## Consequences

The application connection remains able to perform only its product DML and cannot deliberately act as a privilege-delegation or privileged-function gateway. Security/SOC 2/CSAP evidence can treat ACL changes, role membership administration, role creation, replication administration, destructive relation authority, and privileged user-schema routines as operator-owned changes rather than hidden application behavior.

The check is intentionally authority-based rather than body-based. This is stricter for deployments that intentionally expose privileged user-schema functions to the same runtime identity: those deployments must separate the function behind another role/connection or remove the executable edge. That operational cost is preferred to claiming tenant/application least authority while the same login can exercise or redistribute operator authority.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: 5.9. Row security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: 21.2. Role attributes*. https://www.postgresql.org/docs/18/role-attributes.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: 21.3. Role membership*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: GRANT*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026f). *PostgreSQL 18 documentation: SET ROLE*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026g). *PostgreSQL 18 documentation: CREATE FUNCTION*. https://www.postgresql.org/docs/18/sql-createfunction.html

PostgreSQL Global Development Group. (2026h). *PostgreSQL 18 documentation: CREATE ROLE*. https://www.postgresql.org/docs/18/sql-createrole.html

PostgreSQL Global Development Group. (2026i). *PostgreSQL 18 documentation: CREATE DATABASE*. https://www.postgresql.org/docs/18/sql-createdatabase.html

PostgreSQL Global Development Group. (2026j). *PostgreSQL 18 documentation: System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026k). *PostgreSQL 18 documentation: System administration functions*. https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026l). *PostgreSQL 18 documentation: pg_roles*. https://www.postgresql.org/docs/18/view-pg-roles.html
