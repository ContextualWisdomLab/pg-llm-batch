# ADR 0026: Lifecycle Outbox CHECK-Semantics Authority

- Status: Proposed
- Date: 2026-09-06
- Updated: 2026-09-08
- Owners: pg-llm-batch

## Context

`public.llm_context_lifecycle_outbox` is the pg-llm-batch durability boundary for tenant-scoped lifecycle publication intent. Migration 0008 converges the package-owned payload, valid-time, and system-time CHECKs by comparing live PostgreSQL parser output with same-runtime temporary probe expressions. Migration 0009 is the final row-admission gate after that convergence.

Fresh review first found that migration 0009 admitted the three CHECKs by name plus `convalidated` and inheritance flags, without re-reading their Boolean expressions. That creates a restore/operator-drift gap when migration 0008 has already been recorded as applied: an operator can drop one canonical CHECK and recreate a stricter or otherwise different expression under the same canonical name. PostgreSQL stores a CHECK expression in `pg_constraint.conbin`; the name is not semantic identity, and PostgreSQL explicitly documents that constraint names are not necessarily unique. A changed CHECK can reject an otherwise canonical insert or update.

Runtime review then found a second identity gap after deparse equality had been added. PostgreSQL name resolution is affected by `search_path`. When `pg_catalog` is explicitly placed later in that path, an earlier user schema can supply an unqualified operator or function token. A hostile CHECK can therefore bind its stored parse tree to a user-schema object while `pg_get_expr(...)` renders a same-deparse expression that is visually identical to the reviewed canonical predicate. Text equality proves a deparser representation; it does not by itself prove the referenced object OIDs.

PostgreSQL records dependencies between database objects in `pg_catalog.pg_depend`. A normal dependency (`DEPENDENCY_NORMAL`, catalog `deptype = 'n'`) records that one separately created object depends on another object and therefore supplies the missing object-identity evidence for a CHECK that binds to a user-defined operator, function, type, or similar whole object. Pinned built-in system objects need not have ordinary dependency rows, which is expected for the canonical catalog-backed predicate.

The active container target remains PostgreSQL 16. PostgreSQL 18 documentation is used as the latest primary catalog/interface reference for `pg_constraint`, `pg_get_expr`, schema search-path resolution, and `pg_depend` semantics exercised by the PostgreSQL 16 container contract.

## Decision

Migration 0009 independently derives parser-normalized expressions for the canonical payload, valid-time, and system-time CHECKs from a session-local temporary probe table on the same PostgreSQL runtime.

The final row-admission gate admits a CHECK only when all of the following are true:

- it has the exact package-owned canonical name;
- it is a validated inheritable CHECK; and
- `pg_get_expr(conbin, conrelid, false)` exactly equals the corresponding same-runtime canonical probe expression.

The probe table is dropped before production admission continues. The final gate does not repair a mismatched CHECK. Migration 0008 owns convergence; migration 0009 owns fail-closed final verification. This preserves a single repair authority while ensuring restore/operator drift cannot turn a canonical name into semantic authority.

Runtime admission adds a continuing object-identity check because it does not rewrite the caller's `search_path`. For each admitted canonical CHECK, `_unsafe_outbox_constraint_sql()` joins the CHECK object to `pg_catalog.pg_depend` through `classid = 'pg_catalog.pg_constraint'::regclass`, its exact constraint OID, and whole-object `objsubid = 0`. Any whole-object normal dependency (`DEPENDENCY_NORMAL`, `deptype = 'n'`) is rejected before tenant binding or outbox data SQL. The canonical expression must therefore satisfy both deparse equality and the dependency-identity boundary. A same-deparse predicate that resolved to a user-schema shadow operator is not canonical authority merely because its displayed SQL matches.

Unknown or drifted constraints are not auto-dropped by migration 0009 or runtime admission. Their ownership and data-validity consequences require explicit operator reconciliation or reapplication of the package-owned convergence migration.

Package migration 0009 and its Docker initializer must remain byte-identical. This runtime repair does not duplicate convergence authority into a new migration and does not mutate caller name-resolution state.

## Alternatives rejected

Trusting canonical constraint names was rejected because names identify catalog objects, not their Boolean semantics.

Trusting only `convalidated` was rejected because validation says PostgreSQL has checked a particular stored expression; it does not prove that expression is the package-owned lifecycle grammar.

Trusting only `pg_get_expr(...)` equality was rejected by the same-deparse hostile-operator specimen. Deparse text is a useful semantic fixture but is not sufficient object identity when a user-schema object can resolve to the same unqualified token.

Forcing or rewriting the runtime caller's `search_path` was rejected. The outbox contract deliberately does not mutate caller name-resolution state, and changing an ambient transaction setting would create a second authority surface for host code. Runtime admission instead authenticates the stored CHECK's dependency identity directly.

Allow-listing operator or function names was rejected because a name is not an object OID. It would repeat the same identity error at another layer and would be sensitive to caller schema ordering.

Copying a hard-coded deparser string into migration 0009 was rejected because PostgreSQL decompiled expression text can be version-sensitive. A same-runtime temporary probe follows the existing migration-0008 strategy and binds comparison to the parser/catalog representation actually in use.

Automatically repairing or dropping a mismatched CHECK in migration 0009 was rejected because 0008 already owns convergence. Duplicating repair authority would create two mutable convergence implementations and make migration-order evidence harder to reason about.

## Verification

The original final-migration semantics lineage remains:

- test-first commit `d0f52e780d298c92ced71adae8523ae8d48e19ad` adds a real PostgreSQL specimen and wires it into the container CI lane;
- the specimen replaces `ck_llm_context_lifecycle_outbox_payload_canonical_v1` with the same name but a stricter predicate, proves that the replacement rejects an otherwise canonical lifecycle event, then requires migration 0009 itself to fail with the fixed content-free row-admission authority error; and
- causal fix `47ccd293d54fd28e51090aca39af285346673f0a` adds same-runtime payload/valid-time/system-time probe expressions to both byte-identical migration-0009 copies and requires exact expression equality at final admission.

The runtime object-identity extension has independent executable evidence:

- exact head `65af95eed4e3b3bd954aa15898d5da6df8fa6e0c` creates a user-schema regex operator under `search_path = public, pg_catalog`, recreates the canonical-named payload CHECK through that operator, proves that canonical and hostile `pg_get_expr(...)` strings are identical, and requires runtime admission to reject it;
- hosted CI `34160772284`, PostgreSQL/container job `101862006343`, is RED exactly at `Verify lifecycle-outbox CHECK deparse fixture identity` because runtime returned `(False,)`, admitting the hostile same-deparse CHECK;
- causal production fix `6c1ac32143cce1133c3747b0096375bfdbc47a0c` adds only the whole-object NORMAL-dependency probe to runtime constraint authority; exact CI `34161181364` and Release Acceptance `34161181354` both completed successfully, including the same-deparse fixture and the complete existing PostgreSQL security-smoke sequence; and
- owner-contract RED `7d0686177032f08fcc4c292dece11a1b67ff4153`, CI `34161489139`, then required AGENTS, CLAUDE, and this ADR to retain CHECK dependency identity. Python 3.10 reported `3 failed, 1638 passed, 7 deselected` before this documentation repair.

This ADR remains Proposed until the protected integration path completes normally. Predecessor, canceled, synthetic, or mutable-branch evidence is not transferable release authority.

## Consequences

Runtime CHECK admission now performs an additional `pg_catalog.pg_depend` lookup. That catalog read is part of the real buyer path and must remain inside #307's connection-acquisition through admission, tenant-binding, data-I/O, and cleanup p50/p95/p99 measurements. It must not be removed from timing as security overhead.

The selected rule is intentionally fail closed for a canonical CHECK with a whole-object normal dependency. A future legitimate package predicate that intentionally depends on a non-pinned separately created object would require an explicit versioned contract change, a new hostile/control fixture, and a reviewed identity allowlist rather than silently widening this boundary.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: 5.5. Constraints*. https://www.postgresql.org/docs/18/ddl-constraints.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: 5.10. Schemas*. https://www.postgresql.org/docs/18/ddl-schemas.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: 9.27. System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: 52.13. pg_constraint*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: 52.18. pg_depend*. https://www.postgresql.org/docs/18/catalog-pg-depend.html

PostgreSQL Global Development Group. (2026f). *PostgreSQL 18 documentation: 52. Catalogs*. https://www.postgresql.org/docs/18/catalogs.html
