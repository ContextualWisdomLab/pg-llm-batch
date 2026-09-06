# Lifecycle outbox MAINTAIN authority

The lifecycle outbox runtime connection is an append-only tenant application identity. Its normal PostgreSQL relation privileges are non-grantable `SELECT` and `INSERT`. PostgreSQL 18 table `MAINTAIN` is not part of that application contract: PostgreSQL defines it as authority to run `VACUUM`, `ANALYZE`, `CLUSTER`, `REFRESH MATERIALIZED VIEW`, `REINDEX`, `LOCK TABLE`, and relation-statistics manipulation functions.

This distinction matters even though `MAINTAIN` is not tenant-row DML. A runtime login that remains `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` and holds only outbox `SELECT`, `INSERT`, and `MAINTAIN` can still take a relation-wide lock. The executable acceptance specimen uses `LOCK TABLE public.llm_context_lifecycle_outbox IN ACCESS EXCLUSIVE MODE NOWAIT` inside an explicit transaction to prove that availability-control authority is real rather than inferred from an ACL string.

Runtime admission therefore treats `MAINTAIN` as forbidden relation/operator authority everywhere the existing authority graph can reach it:

- directly through `CURRENT_USER`, `SESSION_USER`, or a session-selectable/administerable role;
- through a role that the authenticated session can administer and that itself has, or can `SET ROLE` to, `MAINTAIN` authority;
- through the owner of a callable non-system-schema `SECURITY DEFINER` routine; and
- through a role that such a definer owner can administer directly or through the existing all-`SET TRUE` reachability proof.

The implementation uses PostgreSQL's native `pg_catalog.has_table_privilege(role_oid, relation_oid, 'MAINTAIN')`. It does not parse ACL text, infer function bodies, revoke operator grants, or change role membership. A failing admission is an operator-owned authorization repair: remove the maintenance authority from the application principal graph or place maintenance operations behind a separate operator connection.

The boundary is intentionally narrower than a generic ban on PostgreSQL maintenance. Database operators, autovacuum, migration roles, recovery tooling, and other deliberately separated operational identities may still hold the authority they need. The application connection may not.

## Verification lineage

- PostgreSQL specimen `7dcc55fd80eb6f148de1da897d079048e06483bd` grants an otherwise ordinary runtime login only outbox `SELECT`, `INSERT`, and `MAINTAIN`, proves an `ACCESS EXCLUSIVE` lock executes, and requires package admission to reject the identity before tenant data SQL.
- Static RED `6b78cf0c20a6e9deadaa468d272848a8ac4eeea4` requires `MAINTAIN` coverage across the executable authority closure.
- Causal production repair `25867129f37f31a23885658c5b9a7dbe8dbc993e` adds the native privilege checks without widening database mutations.
- CI wiring `5d2a4089f7ef82dc9cc333816d992bb8085e75b6` adds the real PostgreSQL specimen to the container lane.
- ADR 0032 remains Proposed until one unchanged exact repaired head completes the static/unit/coverage/package and PostgreSQL/container acceptance gates.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: GRANT*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: 9.27. System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: 21.5. Predefined roles*. https://www.postgresql.org/docs/18/predefined-roles.html
