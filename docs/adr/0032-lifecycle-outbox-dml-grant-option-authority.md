# ADR 0032: Lifecycle Outbox Delegable and Executable Privilege Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox runtime is an application DML identity. Its normal database contract is tenant-qualified, forced-RLS `SELECT` and `INSERT`; database administration, role administration, replication, relation maintenance/programming, destructive/mutating DML, and privilege delegation remain operator authority.

ADR 0031 already requires the effective/authenticated role closure to reject `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, outbox ownership or exercisable owner authority, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER`. That direct-role check is necessary but not sufficient because PostgreSQL exposes further delegation and executable-authority paths.

PostgreSQL 17 introduced table `MAINTAIN` as relation-wide operational authority. It authorizes `VACUUM`, `ANALYZE`, `CLUSTER`, `REFRESH MATERIALIZED VIEW`, `REINDEX`, and `LOCK TABLE`. A tenant application identity has no product need for those operations. In particular, `LOCK TABLE` can turn a nominally read/append runtime identity into an availability-control principal, while `CLUSTER` and `REINDEX` can take heavyweight relation/index locks. `MAINTAIN` is therefore outside the same runtime envelope as destructive/programming authority even though it does not itself mean tenant-row DML.

The repository's PostgreSQL container currently defaults to PostgreSQL 16, which does not define `MAINTAIN`. A hardening query that invokes `has_table_privilege(..., 'MAINTAIN')` unconditionally would therefore break an already-supported server before examining any tenant authority. Cross-version admission must distinguish absence of the privilege in PostgreSQL 16 from presence of the privilege in PostgreSQL 17+ without adding a second database round trip.

First, object and role authority can be delegated. `SELECT WITH GRANT OPTION` and `INSERT WITH GRANT OPTION` let a principal create new outbox readers/writers. `ADMIN OPTION` on a role lets the administrator grant that role onward. An administered bridge role can itself carry no inherited outbox DML yet have an all-`SET TRUE` membership path to another role that does; once the bridge is granted, the recipient can select the downstream authority.

Second, callable `SECURITY DEFINER` code executes with its owner's privileges rather than its caller's. A caller that is an ordinary forced-RLS role can therefore exercise operator authority through a user-schema function owner. Real specimens in this repository establish distinct executable cases: a non-owner definer with outbox `TRUNCATE`, a `CREATEROLE` definer that can create a cluster role, and a `REPLICATION` definer that can create a physical replication slot. Those are different mechanisms and are not collapsed into an RLS-bypass claim.

Fresh review exposed a further delegation case. The callable definer owner can itself be `NOCREATEROLE` and hold no forbidden outbox privilege directly, but hold membership `ADMIN OPTION` over a bridge role. PostgreSQL treats `ADMIN`, `INHERIT`, and `SET` as distinct membership options. The administrator may grant the administered role onward even when its own membership is `INHERIT FALSE, SET FALSE`. PostgreSQL also prohibits `SET ROLE` while a `SECURITY DEFINER` function is executing, but that restriction does not close this path: the function performs `GRANT` under the owner's authority, returns, and the caller can then use the newly granted role's all-`SET TRUE` path in invoker context.

A subsequent review exposed an independent executable chain. A caller-visible `SECURITY DEFINER` may be owned by an otherwise safe role that has no direct forbidden outbox or cluster authority, while that owner has schema `USAGE` plus `EXECUTE` on a second non-system-schema `SECURITY DEFINER` owned by a role with forbidden authority. The outer routine executes as its owner; that owner can invoke the inner routine; the inner routine then executes as its own owner. A two-hop PostgreSQL specimen proves that an ordinary caller can enter a safe outer definer and reach an inner definer whose owner has outbox `TRUNCATE`, even though the caller cannot execute the inner routine directly. Direct-caller inspection therefore does not describe the full executable principal graph.

`CREATEDB` needs one explicit distinction. Direct runtime identities remain `NOCREATEDB` under ADR 0031. A callable definer owner is not rejected merely for `CREATEDB`, because the product has not established an executable in-function `CREATE DATABASE` path and PostgreSQL prohibits `CREATE DATABASE` inside a transaction block. `CREATEDB` is nevertheless forbidden when it is authority that a callable definer owner can grant onward through membership administration, because the caller may exercise that newly granted role later outside the security-definer call. The implemented guard follows this distinction rather than over-claiming direct executable `CREATEDB` semantics.

## Decision

`_require_rls_application_role()` retains one fail-closed PostgreSQL catalog round trip before tenant binding or outbox data SQL and rejects the following authority.

### Direct relation and object authority

Every role in the existing effective/session-selectable/administerable runtime closure is rejected when it has:

- table- or column-level `SELECT WITH GRANT OPTION`;
- table- or column-level `INSERT WITH GRANT OPTION`; or
- on PostgreSQL 17+, table-level `MAINTAIN`.

The package does not silently revoke those privileges. `MAINTAIN` is checked with PostgreSQL's `has_table_privilege` inquiry rather than ACL-text parsing. Each `MAINTAIN` inquiry is wrapped in a `CASE` guarded by `server_version_num >= 170000`; PostgreSQL 16 therefore selects `ELSE false` and does not evaluate the unsupported privilege inquiry. This retains the existing one-query admission boundary. The expression is intentionally a `CASE` rather than a boolean `AND`: PostgreSQL documents that `CASE` does not evaluate result subexpressions that are not needed, while general expression evaluation order should not be used as a safety contract.

### Authenticated-session role delegation

The authenticated `SESSION_USER` is rejected when it has `MEMBER WITH ADMIN OPTION` over a role that can confer outbox `SELECT`, `INSERT`, or, on PostgreSQL 17+, `MAINTAIN` after being granted onward. An administered role is authority-bearing when it either:

- has effective outbox `SELECT`, `INSERT`, or applicable `MAINTAIN`, including inherited privilege; or
- can `SET ROLE` directly or indirectly through an all-`SET TRUE` path to another role with that authority.

This follows what the authenticated identity can redistribute, not only what its current effective role can exercise.

### Callable `SECURITY DEFINER` authority

For each non-system-schema `SECURITY DEFINER` routine that a selectable/administerable runtime role can execute through schema `USAGE` plus routine `EXECUTE`, admission enters the routine owner's executable-principal closure. The closure is recursive: for every discovered definer owner, admission also follows non-system-schema `SECURITY DEFINER` routines that owner can execute through schema `USAGE` plus routine `EXECUTE`, using `UNION` de-duplication so cyclic routine-owner graphs terminate.

Every discovered definer owner is checked against the same direct authority envelope:

- `SUPERUSER`;
- `CREATEROLE`;
- `REPLICATION`;
- `BYPASSRLS`;
- exact outbox ownership or exercisable owner authority;
- outbox `SELECT WITH GRANT OPTION` or `INSERT WITH GRANT OPTION`;
- on PostgreSQL 17+, outbox `MAINTAIN`; and
- outbox `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, or `TRIGGER`.

The executable-definer membership-administration envelope additionally rejects a discovered definer owner that has `MEMBER WITH ADMIN OPTION` over a role when that administered role either directly carries, or has an all-`SET TRUE` path to, forbidden runtime/operator authority. The target/reachable authority checked by the current implementation includes:

- `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, or `BYPASSRLS`;
- exact/exercisable outbox ownership;
- outbox `SELECT`, `INSERT`, or applicable `MAINTAIN`; and
- outbox `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, or `TRIGGER`.

This target check intentionally uses ordinary `SELECT`/`INSERT` rather than only grant-option forms: after the definer grants the role to the caller, ordinary DML held by that role becomes usable authority. On PostgreSQL 17+, `MAINTAIN` is likewise checked as ordinary authority because the relation-wide operational capability itself is outside the application identity, regardless of whether it is grantable. Likewise, `CREATEDB` is checked on an administered/reachable role because that authority can be granted to the caller for later invoker-context use even though direct callable-definer `CREATEDB` is not currently treated as an executable in-function capability.

The recursive closure is intentionally authority-based rather than function-body-based. PostgreSQL documents `SECURITY DEFINER` as executing with the owner's privileges and `EXECUTE` as the privilege that permits routine invocation. The package does not attempt to prove that an arbitrary PL/pgSQL, SQL, extension, or dynamically executed body currently invokes every routine its owner could invoke; instead it refuses to call a definer when entering that owner principal can continue into another privileged definer principal. This is conservative, but it keeps the application/runtime boundary independent of mutable routine bodies and procedural-language parsing.

The guard uses PostgreSQL's own role/privilege inquiry functions and catalogs, including `pg_proc.prosecdef`, function owner OIDs, `pg_roles` attributes, `has_schema_privilege`, `has_function_privilege`, `pg_has_role(..., 'MEMBER WITH ADMIN OPTION')`, `pg_has_role(..., 'SET')`, `has_table_privilege`, and `has_any_column_privilege`. PostgreSQL-owned `pg_*` schemas and `information_schema` remain outside this user-schema definer guard; operator policy may impose a stricter database-wide prohibition.

The package never auto-revokes ACLs, membership, role attributes, routine execution, schema usage, function ownership, maintenance authority, or replication authority. Repair remains operator-owned.

## Alternatives considered

### Trust RLS because delegated readers/writers are still ordinary roles

Rejected. RLS controls row access; it does not make authorization delegation part of the application bounded context. The runtime has no product need to manufacture additional outbox principals.

### Allow `MAINTAIN` because it is not tenant-row DML

Rejected. PostgreSQL 17+ defines `MAINTAIN` as authority for relation-wide maintenance and locking operations. The realistic PostgreSQL specimen grants only normal `SELECT`, `INSERT`, and `MAINTAIN`, then proves that the runtime identity can take an `ACCESS EXCLUSIVE` table lock. That is operational/availability authority, not required application DML.

### Probe `MAINTAIN` unconditionally on every supported PostgreSQL version

Rejected. The repository's current PostgreSQL image defaults to version 16, whose table privilege vocabulary does not contain `MAINTAIN`. An unconditional inquiry would be a compatibility regression rather than least-privilege enforcement.

### Use `server_version_num >= 170000 AND has_table_privilege(..., 'MAINTAIN')`

Rejected as a control-flow contract. SQL boolean evaluation order is not a reliable mechanism for suppressing a version-inapplicable function call. `CASE` expresses the needed conditional evaluation explicitly and PostgreSQL documents its non-selected result expressions as unevaluated, subject to planning-time constant-folding caveats that do not apply to this role/relation-dependent inquiry.

### Parse `pg_class.relacl` to avoid a version gate

Rejected. PostgreSQL 17 adds ACL abbreviation `m`, but manual ACL parsing would need to reproduce ownership, `PUBLIC`, role inheritance, and effective privilege semantics already implemented by PostgreSQL's privilege inquiry functions. Version-gating the native inquiry is narrower and less error-prone.

### Check only table-level grant options

Rejected. PostgreSQL supports column-level `SELECT` and `INSERT` grants. `has_any_column_privilege(..., '... WITH GRANT OPTION')` covers both table and column forms without parsing ACL text.

### Check only the administered role's immediate DML

Rejected. An administered bridge may have no inherited DML and still have an all-`SET TRUE` path to a DML-bearing or maintenance-bearing role. Granting the bridge reproduces that selectable path for the recipient.

### Reject every `ADMIN OPTION`

Rejected as broader than the causal boundary. Administration of a role with no relevant operator/outbox authority and no relevant `SET` path does not redistribute this bounded context's authority.

### Trust an ordinary caller when the privileged work is behind `SECURITY DEFINER`

Rejected. PostgreSQL executes the routine with its owner's privileges. Caller attributes therefore do not describe the authority used by the function.

### Inspect only `SECURITY DEFINER` routines directly executable by the runtime role

Rejected. A directly callable outer definer can execute as a safe owner that in turn has `EXECUTE` on a second definer owned by a destructive/operator principal. The caller does not need direct `EXECUTE` on the inner routine. Static RED `154d2a60324791cead1e41266e54696ba8d51650` and the PostgreSQL chain specimen added in `6c7a4e32e6ccfbb751732af7d3a40e299fb1d8d7` preserve this distinction.

### Reject only superuser, `BYPASSRLS`, or exact-owner definers

Rejected. Real specimens prove ordinary separate function owners can hold `TRUNCATE`, `MAINTAIN`, `CREATEROLE`, or `REPLICATION` without satisfying those three predicates.

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
- PostgreSQL/container CI wiring `fb6c3bba7aad728290f0be27e9591888c0584cb6`;
- nested callable-definer closure static RED `154d2a60324791cead1e41266e54696ba8d51650`;
- recursive executable-owner causal repair `a4a4e11381e6bcd6700ddf7ab2fbe945536b81a1`;
- real nested-definer PostgreSQL specimen `6c7a4e32e6ccfbb751732af7d3a40e299fb1d8d7`;
- PostgreSQL/container CI wiring `2f8a2fc0f80c83fa2219980ea522f5077380085f`.

### Relation-maintenance authority

- initial specimen `7dcc55fd80eb6f148de1da897d079048e06483bd` established the intended PostgreSQL-17+ `MAINTAIN`/lock threat model but incorrectly targeted the repository's PostgreSQL-16 image; it is RED lineage, not accepted executable evidence;
- static admission RED `6b78cf0c20a6e9deadaa468d272848a8ac4eeea4` requires `MAINTAIN` rejection across selectable, administered/`SET`-reachable, callable-definer-owner, and definer-admin authority paths;
- first repair `25867129f37f31a23885658c5b9a7dbe8dbc993e` added PostgreSQL-native `has_table_privilege(..., 'MAINTAIN')` checks but was rejected by self-review before GREEN because PostgreSQL 16 does not recognize that privilege name;
- compatibility RED `c7310bc9aa2abea9bf6e05b015380740517c6b2f` requires every emitted `MAINTAIN` inquiry to be protected by a PostgreSQL-17+ `CASE` gate;
- causal cross-version repair `fd9dc22bb1d6e4632fa1c268dd6bfadd0a442de2` centralizes the version-safe native inquiry and retains one admission round trip;
- executable acceptance repair `9f0c6a688051b7a84a900aa01203f2203724dd2a` runs migration and adapter behavior on digest-pinned PostgreSQL 18, proves `ACCESS EXCLUSIVE` locking with only `SELECT`, `INSERT`, and `MAINTAIN`, requires package rejection, revokes only `MAINTAIN`, and requires the same login to pass as a positive control;
- PostgreSQL/container CI wiring `5d2a4089f7ef82dc9cc333816d992bb8085e75b6` executes that specimen while the ordinary container suite continues to exercise the same admission SQL on the repository's PostgreSQL-16 image;
- focused doctoring update `89d6dbaad763eb1805c745f1f453fe2da0515374` records the cross-version authority and acceptance boundary.

The nested-definer specimen gives the outer owner no forbidden outbox or cluster authority and revokes the inner routine from `PUBLIC`. Only the outer owner has `EXECUTE` on the inner routine; only the ordinary runtime caller has `EXECUTE` on the outer routine. Calling the outer routine as the runtime user proves the inner owner's RLS-exempt `TRUNCATE` can empty the outbox. The specimen restores a canonical row, requires package admission to reject the latent nested executable edge, then revokes the outer owner's inner-routine `EXECUTE` and requires the same ordinary runtime store to load its tenant row successfully as a positive control.

The admin-delegation specimen deliberately gives the definer owner no `CREATEROLE` and no direct destructive relation privilege. It grants an `INHERIT FALSE, SET FALSE` bridge that has `SET TRUE` to an outbox `TRUNCATE` role, proves the ordinary caller can traverse the newly granted role chain and empty the outbox, revokes the caller's materialized bridge membership, and then requires package admission to reject the still-callable latent authority. That separates the causal defect from both direct definer privileges and already-materialized caller authority.

Earlier heads, partial jobs, and superseded workflow runs are lineage only. ADR 0032 remains Proposed until one unchanged exact repaired head executes the static contracts, full unit/coverage gates, the normal PostgreSQL-16 container suite, and the digest-pinned PostgreSQL-18 `MAINTAIN` specimen successfully.

## Consequences

The application connection remains able to perform only its product DML and cannot deliberately act as a privilege-delegation, relation-maintenance, or privileged-function gateway. Security/SOC 2/CSAP evidence can treat ACL changes, role membership administration, role creation, replication administration, relation maintenance/destructive authority, and privileged user-schema routines as operator-owned changes rather than hidden application behavior.

PostgreSQL 16 remains a supported runtime without pretending that a PostgreSQL-17 privilege exists there. PostgreSQL 17+ deployments gain the stricter relation-maintenance check from the same source path. The check is intentionally authority-based rather than body-based. This is stricter for deployments that intentionally expose privileged user-schema functions or relation-maintenance privileges to the same runtime identity or to an owner principal reachable through such a function: those deployments must separate the authority behind another role/connection or remove the executable edge. That operational cost is preferred to claiming tenant/application least authority while the same login can enter an executable principal graph that reaches operator authority.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 16 documentation: 5.7. Privileges*. https://www.postgresql.org/docs/16/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 16 documentation: 9.18. Conditional expressions*. https://www.postgresql.org/docs/16/functions-conditional.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 17 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/17/ddl-priv.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: 5.9. Row security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: 21.2. Role attributes*. https://www.postgresql.org/docs/18/role-attributes.html

PostgreSQL Global Development Group. (2026f). *PostgreSQL 18 documentation: 21.3. Role membership*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026g). *PostgreSQL 18 documentation: GRANT*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026h). *PostgreSQL 18 documentation: SET ROLE*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026i). *PostgreSQL 18 documentation: CREATE FUNCTION*. https://www.postgresql.org/docs/18/sql-createfunction.html

PostgreSQL Global Development Group. (2026j). *PostgreSQL 18 documentation: CREATE ROLE*. https://www.postgresql.org/docs/18/sql-createrole.html

PostgreSQL Global Development Group. (2026k). *PostgreSQL 18 documentation: CREATE DATABASE*. https://www.postgresql.org/docs/18/sql-createdatabase.html

PostgreSQL Global Development Group. (2026l). *PostgreSQL 18 documentation: System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026m). *PostgreSQL 18 documentation: System administration functions*. https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026n). *PostgreSQL 18 documentation: pg_roles*. https://www.postgresql.org/docs/18/view-pg-roles.html

PostgreSQL Global Development Group. (2026o). *PostgreSQL 18 documentation: LOCK*. https://www.postgresql.org/docs/18/sql-lock.html

Docker. (2026). *postgres:18-bookworm image manifest, sha256:33c86c9cfb790e257e470b29e8c97bd1bd6fee0a70ab2d7a2e377ab639c09935*. Docker Hub.
