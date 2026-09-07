# ADR 0034: Session-Admin Role Authority Closure

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox runtime credential is intentionally narrower than a general PostgreSQL role. It may hold only the non-grantable application privileges needed for tenant-scoped outbox reads and inserts while forced RLS, the canonical tenant policy, append-only durability, and operator separation remain live.

PostgreSQL 18 separates role membership into `INHERIT`, `SET`, and `ADMIN` options. `SET TRUE` permits `SET ROLE` along a membership path. `ADMIN OPTION` is different: the administrator may grant the administered role to another principal and choose the new membership options. Consequently, a currently non-selectable role is not outside a session's future authority when a role that the session can already become owns `ADMIN OPTION` over it.

The previous admission query handled two shallower cases but did not compute that future authority transitively. It rejected a role directly selectable by `SESSION_USER`, and it rejected a role that `SESSION_USER` itself could make selectable through `MEMBER WITH ADMIN OPTION`. It also checked one all-`SET` descendant layer. That left a gap when a session could `SET ROLE` to an otherwise safe outer role, the outer role held `ADMIN OPTION` over an inner role with `SET FALSE`, and that inner role led through a `SET TRUE` edge to destructive or opaque authority. While acting as the outer role, the authenticated session could grant the inner role back to itself with `SET TRUE`, reset to the login identity, select the newly granted role, and continue through the destructive path.

Test-first exact head `e5df5ab29d746160007a2cabfcf6a81b6ac9af79` preserves the gap. The structural contract requires a cycle-safe `pg_auth_members` closure over both `set_option` and `admin_option`; hosted CI run `34090079120` failed on that contract before the causal repair. The PostgreSQL specimen `tests/smoke_context_lifecycle_outbox_role_admin_destructive_authority.sh` uses an ordinary `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` login, an outer role selectable by that login, an inner role administered by the outer role with `INHERIT FALSE, SET FALSE`, and a leaf with `TRUNCATE` on the lifecycle outbox. Before the grant, the login cannot `SET ROLE` to the inner role. The outer role can nevertheless grant the inner role to the login with `SET TRUE`; the login can then reach the leaf and truncate the outbox. Missing current `SET` authority is therefore not durable safety evidence.

This finding is independent of foreign-data authority, although the same closure can lead to ordinary views, materialized copies, inheritance/partition parents, foreign tables, owner authority, grant options, or role attributes. The authority boundary must therefore be computed before choosing which forbidden capability to test.

## Decision

For every runtime principal already reachable from `CURRENT_USER` or authenticated `SESSION_USER`, admission computes the future role-selection closure through `pg_catalog.pg_auth_members` using a cycle-safe recursive CTE. From any reachable role, either of these membership edges makes the granted role reachable:

1. `set_option = true`, because the current principal may select the granted role directly; or
2. `admin_option = true`, because the current principal may grant the administered role to the authenticated login with `SET TRUE`, after which that role becomes selectable.

The recursive step repeats from each newly reachable role. It therefore covers mixed paths such as `SET -> ADMIN -> SET -> ADMIN`, rather than assuming that only the authenticated login itself can exercise membership administration.

Every discovered role is evaluated against the same forbidden application-role envelope used for directly selectable principals: `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, exact or effective outbox-owner authority, owner membership/selection/administration, `SELECT` or `INSERT` including grant options, PostgreSQL 17+ `MAINTAIN`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, `TRIGGER`, and the existing reachable ordinary-view/materialized-copy/inheritance/foreign-data authority probe. The guard remains fail closed before tenant binding or lifecycle-outbox data SQL.

The package does not mutate role membership to make the credential safe. Operators must separate administration and application identities. The admission query only proves that the presented runtime credential cannot already select, or make selectable through its reachable administrators, a principal carrying forbidden authority.

This decision extends the runtime-role authority model; it does not weaken ADR 0033's opaque foreign-data boundary or the callable `SECURITY DEFINER` boundary. Those authority graphs remain additional checks after the session role closure is established.

## Alternatives considered

### Trust the authenticated login's current `SET ROLE` closure

Rejected. The executable specimen starts with no login-to-inner `SET` path, yet a role the login can select holds `ADMIN OPTION` over the inner role and can grant it back with `SET TRUE`.

### Inspect only `MEMBER WITH ADMIN OPTION` held directly by `SESSION_USER`

Rejected. `ADMIN OPTION` can be exercised after `SET ROLE` to another reachable role. Limiting administration to the login identity misses mixed `SET -> ADMIN` paths.

### Check only one administered role plus its current all-`SET` descendants

Rejected. Role administration can recur. A newly reachable role may itself administer another role, so a bounded one-hop expansion is not a stable authorization proof.

### Reject only delegated `SELECT`, `INSERT`, or `MAINTAIN`

Rejected. The reproduced path terminates in `TRUNCATE`, which is relation-wide and outside RLS. The same membership closure can terminate in grant options, owner authority, role attributes, relation programming, copied data, or foreign-data authority. The authority graph and the forbidden-capability envelope are separate concerns.

### Revoke or rewrite memberships automatically

Rejected. pg-llm-batch does not own database authorization policy. Runtime admission reports an unsafe credential; operators repair roles and memberships through their identity/database administration process.

## Verification

- Flat ADMIN-delegation RED: exact test/wiring head `30f08573d9a1b134e1805a1288a96cbe097b70fc`, CI `34089249735`; PostgreSQL/container job `101639228718` reached the new destructive-delegation smoke after the prior role-admin DML smoke and failed because production admitted a role that could make a `TRUNCATE` path selectable.
- Flat causal repair: `bb83143e2a38c580b9a40f18276723389a36e92e` extended the delegated role's forbidden envelope to role flags, owner authority, grant options, destructive/programming privileges, and the existing relation/view/materialized/inheritance/foreign-data probe.
- Recursive ADMIN RED: exact `e5df5ab29d746160007a2cabfcf6a81b6ac9af79`, CI `34090079120`. Python 3.10 job `101641649336` failed after the new structural contract required recursive `pg_auth_members` treatment of both `set_option` and `admin_option`. The executable PostgreSQL specimen is wired into the required container lane under `Run lifecycle-outbox role-admin destructive-delegation smoke`.
- Recursive causal repair: `51895a76aa3cac28d17e91f0d19910c99f5da8fe` replaces the bounded delegated-role lookup with a cycle-safe recursive `delegated_role(role_oid)` closure over `pg_auth_members`, where either `set_option` or `admin_option` advances reachability. Every non-seed role then receives the same forbidden authority checks as the prior delegated role.
- Existing RLS-policy, session/effective-role, grant-option, `MAINTAIN`, `SECURITY DEFINER`, ordinary-view, materialized-copy, foreign-data, inheritance/partition, replay, migration, coverage, packaging, and release-acceptance gates remain mandatory.
- This ADR remains Proposed until one unchanged exact PR head containing the repair and this decision passes hosted CI and Release Acceptance and is integrated through the protected-branch workflow.

## Operational effect

Issue #307's buyer-performance acceptance must include this recursive authorization cost. Measurements from connection acquisition through cleanup must vary the number of session-selectable roles, membership depth, `SET`/`ADMIN` branching factor, mixed `SET -> ADMIN -> SET` paths, and the relation/view/materialized/inheritance/foreign authority probes executed for reachable principals. Security admission may be optimized from measured planner/catalog evidence, but it may not be removed from the p50/p95/p99 path, pruned to an unrealistic role graph, or measured only after a privileged warm-cache setup.

## References

PostgreSQL Global Development Group. (n.d.). *GRANT*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (n.d.). *Role membership*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (n.d.). *Role attributes*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/role-attributes.html

PostgreSQL Global Development Group. (n.d.). *SET ROLE*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-set-role.html
