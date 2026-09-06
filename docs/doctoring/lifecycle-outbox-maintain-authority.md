# Lifecycle outbox MAINTAIN authority

The lifecycle outbox runtime connection is an append-only tenant application identity. Its normal PostgreSQL relation privileges are non-grantable `SELECT` and `INSERT`. PostgreSQL 17 introduced table `MAINTAIN`; PostgreSQL defines it as authority to run `VACUUM`, `ANALYZE`, `CLUSTER`, `REFRESH MATERIALIZED VIEW`, `REINDEX`, and `LOCK TABLE` on a relation. That authority is not part of the application contract.

This distinction matters even though `MAINTAIN` is not tenant-row DML. A runtime login that remains `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` and holds only outbox `SELECT`, `INSERT`, and `MAINTAIN` can still take a relation-wide lock. The executable acceptance specimen uses `LOCK TABLE public.llm_context_lifecycle_outbox IN ACCESS EXCLUSIVE MODE NOWAIT` inside an explicit transaction to prove that availability-control authority is real rather than inferred from an ACL string.

Runtime admission therefore treats `MAINTAIN` as forbidden relation/operator authority everywhere the existing authority graph can reach it:

- directly through `CURRENT_USER`, `SESSION_USER`, or a session-selectable/administerable role;
- through a role that the authenticated session can administer and that itself has, or can `SET ROLE` to, `MAINTAIN` authority;
- through the owner of a callable non-system-schema `SECURITY DEFINER` routine; and
- through a role that such a definer owner can administer directly or through the existing all-`SET TRUE` reachability proof.

## PostgreSQL 16 compatibility boundary

The repository's production PostgreSQL image currently defaults to PostgreSQL 16. PostgreSQL 16 does not define the `MAINTAIN` table privilege, while PostgreSQL 17 does. An unconditional `has_table_privilege(..., 'MAINTAIN')` call would therefore turn a PostgreSQL-17+ hardening change into a PostgreSQL-16 runtime regression.

The runtime keeps one admission catalog round trip and emits a version-gated expression for each reachable principal. `server_version_num >= 170000` enters a `CASE` arm that invokes `pg_catalog.has_table_privilege(..., 'MAINTAIN')`; PostgreSQL 16 takes the `ELSE false` arm and never evaluates the unsupported privilege probe. PostgreSQL documents `CASE` as not evaluating subexpressions that are not needed to determine its result, subject to planning-time caveats such as constant-folded failures. Here the privilege inquiry depends on live role and relation OIDs and is not a constant-foldable expression.

The executable `MAINTAIN` acceptance therefore does not pretend the PostgreSQL-16 product image can grant a privilege that does not exist there. It runs the package migrations and runtime adapter against a separate digest-pinned PostgreSQL 18 image, proves the real `ACCESS EXCLUSIVE` lock, requires admission failure while `MAINTAIN` is present, revokes only `MAINTAIN`, and then requires the same runtime login to pass admission as the positive control. The normal container suite continues to exercise the same generated admission SQL on the repository's PostgreSQL-16 image, so both sides of the compatibility boundary are covered.

The implementation uses PostgreSQL's native `pg_catalog.has_table_privilege(role_oid, relation_oid, 'MAINTAIN')` only on PostgreSQL 17 or newer. It does not parse ACL text, infer function bodies, revoke operator grants, or change role membership. A failing admission is an operator-owned authorization repair: remove the maintenance authority from the application principal graph or place maintenance operations behind a separate operator connection.

The boundary is intentionally narrower than a generic ban on PostgreSQL maintenance. Database operators, autovacuum, migration roles, recovery tooling, and other deliberately separated operational identities may still hold the authority they need. The application connection may not.

## Verification lineage

- Initial PostgreSQL specimen `7dcc55fd80eb6f148de1da897d079048e06483bd` established the intended `MAINTAIN`/lock threat model but incorrectly reused the repository's PostgreSQL-16 image; self-review rejected that as executable evidence because PostgreSQL 16 has no `MAINTAIN` privilege.
- Static authority RED `6b78cf0c20a6e9deadaa468d272848a8ac4eeea4` requires `MAINTAIN` coverage across the executable authority closure.
- Initial production repair `25867129f37f31a23885658c5b9a7dbe8dbc993e` added native privilege checks, but self-review found the same cross-version defect before exact-head GREEN was claimed.
- PostgreSQL-16 compatibility RED `c7310bc9aa2abea9bf6e05b015380740517c6b2f` requires every generated `MAINTAIN` inquiry to sit behind a `server_version_num >= 170000` `CASE` guard.
- Causal compatibility repair `fd9dc22bb1d6e4632fa1c268dd6bfadd0a442de2` centralizes that version-safe privilege expression while retaining the existing one-round-trip admission boundary.
- Executable acceptance repair `9f0c6a688051b7a84a900aa01203f2203724dd2a` moves the real `MAINTAIN` specimen to digest-pinned PostgreSQL 18 and adds the revoke-only positive control; ordinary repository PostgreSQL-16 smokes remain the backward-compatibility control.
- CI wiring `5d2a4089f7ef82dc9cc333816d992bb8085e75b6` executes the cross-version specimen in the PostgreSQL/container lane.
- ADR 0032 remains Proposed until one unchanged exact repaired head completes the static/unit/coverage/package, PostgreSQL-16 container suite, and digest-pinned PostgreSQL-18 `MAINTAIN` acceptance.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 16 documentation: 5.7. Privileges*. https://www.postgresql.org/docs/16/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 16 documentation: 9.18. Conditional expressions*. https://www.postgresql.org/docs/16/functions-conditional.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 17 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/17/ddl-priv.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: LOCK*. https://www.postgresql.org/docs/18/sql-lock.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: GRANT*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026f). *PostgreSQL 18 documentation: System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

Docker. (2026). *postgres:18-bookworm image manifest, sha256:33c86c9cfb790e257e470b29e8c97bd1bd6fee0a70ab2d7a2e377ab639c09935*. Docker Hub.
