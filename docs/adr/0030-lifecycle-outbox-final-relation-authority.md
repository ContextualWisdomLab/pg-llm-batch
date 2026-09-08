# ADR 0030: Lifecycle Outbox Final Relation Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle durability boundary

## Context

Migration 0008 converges `public.llm_context_lifecycle_outbox` to one ordinary logged table with no PostgreSQL inheritance edge. Migration 0009 is the later fail-closed row-admission verifier used to prove that the current relation still has only reviewed durability, storage, and write authorities before pg-llm-batch treats it as durable publication intent.

Before this decision, migration 0009 independently re-proved RLS, table programs, complete column identity, omitted-column defaults, CHECK semantics, constraints, and index programs, but it did not re-prove the relation's `pg_class.relkind` / `relpersistence`, schema identity, `pg_inherits` topology, or table access-method identity after 0008 had been recorded as applied.

That gap is material. PostgreSQL documents that UNLOGGED table data is not written to WAL, is not crash-safe, is truncated after a crash or unclean shutdown, and is not replicated to standby servers. PostgreSQL inheritance also changes the relation boundary: parent queries generally include child rows unless `ONLY` is used, while UNIQUE and PRIMARY KEY constraints are not inherited and do not enforce uniqueness across the hierarchy.

Table access method identity is a separate storage authority. `pg_class.relam` selects the relation access method, `pg_am` binds that access method to its handler, and PostgreSQL's table-AM interface delegates storage behavior to callbacks supplied by that handler. PostgreSQL permits an existing table to be rewritten with `ALTER TABLE ... SET ACCESS METHOD`, and entirely new table access methods can be supplied by add-on code. A later access-method change can therefore replace storage behavior without changing the already-reviewed columns, RLS policies, CHECKs, UNIQUE constraints, defaults, triggers/rules, or index definitions.

The same authority is mutable after both migrations finish. A restore or privileged operator can change the already-admitted relation to UNLOGGED, attach an inheritance child, or select another TABLE access method while leaving the RLS policy, constraints, defaults, indexes, triggers/rules, and application-role graph otherwise canonical. Treating migration 0009 as transferable runtime evidence would therefore let the durable outbox continue operating on storage/topology that the current catalog no longer authorizes.

The repository currently executes PostgreSQL 16 in its container acceptance profile. Current PostgreSQL 18 documentation is the primary specification for these durability, inheritance, and access-method semantics; executable acceptance remains bound to the repository's actual supported image.

## Decision

Migration 0008 remains the sole convergence owner. Migration 0009 remains final verification and must not repair post-convergence relation drift. Runtime admission independently re-proves the same mutable relation identity before tenant binding and data I/O; migration success is not a capability token for later calls.

Before RLS and later row-admission checks, migration 0009 and runtime `_require_rls_application_role()` must prove that the canonical object:

- resolves exactly as `public.llm_context_lifecycle_outbox`;
- is an ordinary relation (`pg_class.relkind = 'r'`);
- is permanently/WAL logged (`pg_class.relpersistence = 'p'`);
- belongs to schema `public`;
- uses the PostgreSQL built-in `heap` table access method (`pg_class.relam -> pg_am.amname = 'heap'`, `pg_am.amtype = 't'`); and
- participates in no `pg_inherits` edge as either child or parent.

Migration mismatch raises the existing content-free `unexpected lifecycle outbox row-admission authority` error. Runtime mismatch raises the existing separated-authority `ConfigError` before tenant `set_config` or durable row SQL. Neither path executes `SET LOGGED`, `SET ACCESS METHOD`, detach/attach inheritance, copy/delete data, or rebuilds the relation.

Runtime performs the relation proof inside the same live admission catalog statement that already proves RLS, table programs, constraints/defaults, policy dependency identity, role/delegation closure, and callable/view/foreign authority. It joins `pg_namespace` and `pg_am` by the admitted `pg_class` row and checks `pg_inherits` against that same relation OID. This avoids an additional admission round trip and keeps the new catalog work inside the buyer-path performance envelope owned by issue #307. The read/write paths already acquire their relation lock before this proof and retain the exact admitted OID through consuming data SQL, so conflicting table-level DDL cannot make the storage/topology verdict stale between admission and I/O.

Real PostgreSQL acceptance must first change the already-converged outbox to UNLOGGED, prove the catalog state actually changed, require both continuing runtime admission and migration 0009 to fail closed, explicitly restore LOGGED, and require both forms of re-admission to succeed. It must separately attach a post-convergence inheritance child, prove the edge exists, require both runtime and migration 0009 to fail closed, then explicitly remove the child and require clean re-admission.

Access-method acceptance must create a test-only TABLE access-method alias using PostgreSQL's built-in heap handler, rewrite the already-converged outbox to that non-canonical access-method identity, prove `pg_class.relam` now resolves to the alias, require both runtime and migration 0009 to fail closed, then explicitly rewrite the test relation back to `heap`, remove the alias, and require clean re-admission. The alias keeps the specimen independent of external extensions; it proves the catalog-identity gap, while the PostgreSQL table-AM contract establishes why accepting arbitrary handlers would admit unreviewed storage behavior.

## Alternatives considered

Trusting migration 0008 or migration 0009 history was rejected because a successful earlier convergence/admission is not evidence of current relation persistence, topology, or storage implementation after restore/operator DDL.

Checking only `relpersistence` was rejected because an inheritance edge can widen ordinary parent-table operations beyond the single aggregate table while leaving persistence logged, and a table access-method change can replace storage callbacks while leaving both persistence and topology unchanged.

Allowing any TABLE access method was rejected because pg-llm-batch has tested and documented recovery, WAL, replay, and operational behavior for the repository's heap-backed PostgreSQL profile, not for arbitrary add-on `TableAmRoutine` implementations.

Checking only `pg_am.amtype = 't'` was rejected because that proves category, not implementation identity. The final verifier and runtime admission require the reviewed built-in `heap` access-method name as well.

Relying only on runtime `ONLY` reads was rejected because the package owns more than one database operation and migration/recovery/replay authority must remain one canonical physical relation rather than a hierarchy whose constraints have different inheritance semantics.

Relying only on the runtime relation OID/name-rebinding proof was rejected because it authenticates which relation object is consumed, not whether that same object is still logged, heap-backed, and topology-isolated. Object identity and storage authority are distinct invariants.

Automatically executing `ALTER TABLE ... SET LOGGED` or `ALTER TABLE ... SET ACCESS METHOD heap` was rejected because both can imply storage/WAL rewrite work with availability and recovery consequences, and no final verifier can reconstruct durable intents already lost or altered under an unreviewed storage regime.

Automatically dropping or detaching inheritance children was rejected because the package cannot prove ownership, data-retention obligations, or whether child rows contain independently authoritative records.

## Verification and traceability

The TDD/evidence lineage for this decision is:

- static relation RED `3b0e6937e13988e091a21599ac5d1c91dc4e5cfb`, requiring migration 0009 to re-prove logged ordinary-public relation identity and absence of inheritance edges;
- executable relation RED `29afc8d155fc9efcc5e2fa9778f1809de4434721`, refined by `a00f2c65b1a8576c5403d080d5806a66e32c46f7`, covering post-0008 UNLOGGED and inheritance drift;
- original CI wiring `6407be7dde493bfea343ff16b8bd143da36f0d78`;
- original package relation repair `c2a170532fb5fb65cc3994a113f6a53fbeec2c18` and Docker mirror `f1a44358662396db091f77f660d1e3647c0625ab`;
- table-access-method static RED `0b218adb1f511c09998655973cc22cbd5810f251`, requiring migration 0009 to bind the relation to the reviewed heap TABLE access method;
- executable PostgreSQL access-method specimen `6fb5f4b911ce35ee9f63ff3531e0de17041db4f3`, reproducing post-convergence `relam` drift and requiring fail-closed admission;
- package access-method repair `e6d7664e990e29b8e72c3d68094375a3b17dac76`; and
- byte-identical Docker mirror repair `81ee4677e2d92cc7e094228142d90490e7f09171`.

Continuing-runtime parity is proven separately rather than inferred from those migration checks:

- runtime executable RED `2322fcdff613ae587bbb83b648f7b6103c7dd4cc` extends the real PostgreSQL final-relation specimen so the same ordinary `NOSUPERUSER NOBYPASSRLS` application role must reject post-migration UNLOGGED, inheritance, and alternate table-AM drift;
- hosted CI `34185971653`, PostgreSQL/container job `101934245653`, failed on that exact RED with `AssertionError: runtime admitted post-migration UNLOGGED durability drift`, while migration 0009 still rejected the drift as designed;
- minimal production repair `fa9f61de2a643f70272dc5fdbda7c35a4fb09647` adds the ordinary/logged/public/heap/no-inheritance predicates to the existing runtime catalog admission statement without changing migration convergence, tenant binding, RLS policy, or data SQL; and
- descendant unit contract `e5f539124dc4e038efa4c390e012f29fdde6a576` pins those SQL predicates and catalog joins so later refactors cannot silently return to migration-history trust.

This ADR remains Proposed until one unchanged exact head executes the hosted PostgreSQL/container specimens and the complete repository quality/release acceptance set. Queued, pending, stale, predecessor, or otherwise non-executed evidence does not promote this decision to Accepted.

## Consequences

A restore/operator that intentionally changes lifecycle-outbox persistence, inheritance topology, or table access method must reconcile the database explicitly before pg-llm-batch admits it at migration time or at continuing runtime. If an UNLOGGED interval may have crossed a crash or standby failover, operators must reconcile potentially lost publication intents rather than treating `SET LOGGED` as historical recovery evidence. If an unreviewed table access method was active, operators must treat that interval as a storage/recovery-boundary change and establish data/replay integrity before returning the relation to `heap`.

The runtime proof adds `pg_namespace`, `pg_am`, and `pg_inherits` catalog work to every admitted outbox I/O; it is not migration-only overhead. Issue #307 must include this work inside connection acquisition -> relation-lock acquisition/wait -> full live authority admission -> tenant binding -> data I/O -> cleanup p50/p95/p99 measurements under realistic catalog cardinality, connection pressure, and relevant DDL contention. The catalog proof may not be excluded, sampled away, or hidden behind an unrealistic warm-cache-only setup to manufacture the p95 <= 20 ms target.

The change introduces no provider coupling, cross-service SQL, prompt/response retention, or mutable upstream dependency.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: ALTER TABLE*. https://www.postgresql.org/docs/18/sql-altertable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE ACCESS METHOD*. https://www.postgresql.org/docs/18/sql-create-access-method.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Inheritance*. https://www.postgresql.org/docs/18/ddl-inherit.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_am*. https://www.postgresql.org/docs/18/catalog-pg-am.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_class*. https://www.postgresql.org/docs/18/catalog-pg-class.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_inherits*. https://www.postgresql.org/docs/18/catalog-pg-inherits.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Table Access Method Interface Definition*. https://www.postgresql.org/docs/18/tableam.html
