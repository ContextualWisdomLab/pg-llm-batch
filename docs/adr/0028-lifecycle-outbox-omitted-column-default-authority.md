# ADR 0028: Lifecycle Outbox Omitted-Column Default Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle durability boundary

## Context

`PostgresContextLifecycleOutboxStore.enqueue_in_transaction()` supplies the tenant and privacy-minimized lifecycle evidence columns but intentionally omits `context_outbox_uuid` and `created_at`. PostgreSQL therefore evaluates the declared defaults for those two columns on each newly inserted durable publication intent.

The reviewed schema also deliberately retains `tenant_scope DEFAULT 'standalone'` for direct/operator SQL compatibility. Package writes do not rely on that default: the store validates and supplies `tenant_scope` explicitly before executing the insert. The declared default is nevertheless executable schema authority because any direct/operator insert that omits `tenant_scope`, or explicitly uses `DEFAULT`, causes PostgreSQL to evaluate the current default expression.

Migration 0008 owns convergence. It establishes the canonical defaults and verifies them while the schema migration is executing. That evidence is not sufficient for final admission after a restore or later operator DDL: the migration can have been recorded as applied and any declared default can subsequently be replaced without changing the table's CHECK constraints, RLS policy, user-trigger/rule inventory, replay key, or index topology. Before this decision was extended, migration 0009 re-proved the exact defaults for `context_outbox_uuid` and `created_at` but required only the presence of some `tenant_scope` default through `pg_attribute.atthasdef`.

A changed default is executable write-path authority. PostgreSQL permits a column default to be an expression and evaluates it whenever an insert omits the column or asks for `DEFAULT`. A volatile function can therefore reject or alter an otherwise-canonical direct insert even when the visible column shape remains unchanged. `pg_attrdef` stores the default expression in `adbin`; PostgreSQL documents `pg_get_expr(adbin, adrelid)` as the supported SQL representation.

Exact deparse text is necessary but not sufficient authority. A restored or operator-modified default can deparse to the same visible expression while the stored parse tree references a different database object. `pg_depend` records dependency relationships by catalog/OID identity. In particular, a normal dependency (`deptype = 'n'`) proves that the default object is bound to a separately created referenced object; name-equivalent text alone does not prove that the package-owned executable authority is unchanged. The canonical defaults used here do not require such a normal dependency, so admitting one would silently widen executable authority.

The repository currently runs the PostgreSQL 16 container profile. Current PostgreSQL 18 documentation is used as the primary specification because the catalog, dependency, and expression-deparse interfaces relied on here are also present in the supported runtime version; acceptance remains executable against the repository's actual PostgreSQL image.

## Decision

Migration 0008 remains the sole convergence owner. Migration 0009 is a fail-closed final verifier and does not repair operator drift. Runtime `_require_rls_application_role()` is a second, continuing admission boundary: migration success is point-in-time evidence and cannot authorize later default drift.

Before admitting the outbox, migration 0009 and runtime admission must re-read `pg_attribute` and `pg_attrdef` and prove all of the following:

- `tenant_scope` is a live, non-generated, non-identity, NOT NULL `text` column with a default whose deparsed expression is exactly `'standalone'::text`;
- `context_outbox_uuid` is a live, non-generated, non-identity, NOT NULL `uuid` column with a default whose deparsed expression is exactly `gen_random_uuid()`;
- `created_at` is a live, non-generated, non-identity, NOT NULL `timestamp with time zone` column with a default whose deparsed expression is exactly `now()`; and
- any mismatch fails through the existing content-free `unexpected lifecycle outbox row-admission authority` boundary before tenant binding or outbox data SQL.

Runtime admission must additionally authenticate dependency identity for each admitted `pg_attrdef` through `pg_catalog.pg_depend`. Any normal dependency attached to an otherwise text-equivalent canonical default is rejected before tenant binding or outbox data SQL. This deliberately fails closed rather than attempting to infer safety from a function/operator name, schema, `search_path`, or deparsed text.

The package migration and Docker initializer must remain byte-identical. Realistic container acceptance must prove three classes of executable default authority: an operator-supplied `created_at` default can reject a package-shaped insert; an operator-supplied `tenant_scope` default can reject an otherwise-canonical direct insert that omits the tenant column; and a same-deparsed default whose parse tree is bound to a non-canonical object identity must be rejected by runtime admission. After explicit test cleanup and restoration of each canonical default, admission must succeed again.

This does not redefine tenant authorization. The package path continues to derive tenant scope only from the trusted host boundary and supplies it explicitly; the `standalone` default is compatibility schema, not an identity credential or RLS bypass mechanism.

## Alternatives considered

Trust migration history alone was rejected because a successful earlier migration does not prove current catalog authority after restore or later DDL.

Checking only `pg_attribute.atthasdef` was rejected because it proves only that some default exists, not which expression will execute.

Comparing only `pg_get_expr(...)` output was rejected because deparse equality is presentation-level semantic evidence, not dependency identity. A parse tree can retain name-equivalent output while being bound to a different executable object, and `pg_depend` is the catalog authority for those object relationships.

Ignoring `tenant_scope` because the package insert supplies it explicitly was rejected because the repository intentionally keeps `DEFAULT 'standalone'` as part of the supported schema contract. Final admission cannot claim exact catalog authority while accepting arbitrary executable semantics on a retained compatibility surface.

Allow-listing user function names or schemas was rejected because names are mutable metadata and do not establish the package-owned default semantics or referenced-object identity.

Automatically resetting defaults in migration 0009 or runtime admission was rejected because those paths are admission verifiers. Silent repair would erase operator evidence and split convergence authority with migration 0008.

Supplying UUID and timestamp values explicitly from application code was rejected for this repair because it changes the established database-owned durable identity and insertion-time semantics rather than closing the catalog-verification gap.

Removing the `tenant_scope` default was rejected as a separate compatibility-breaking schema decision. This repair verifies the existing contract rather than changing it.

## Verification and traceability

The original omitted-column-default lineage is retained:

- static RED `2706d360847a9acfb231f12a46572b9b964a5168`, requiring final `pg_attrdef` verification in migration 0009;
- executable PostgreSQL RED specimen `0f9120de47de99d4233a1e32a228c14208c0ffc5`, demonstrating that an omitted-column default can execute and reject a canonical event;
- CI wiring `ba7f6a5483f1b3e038deef41baa1b72271278c29`;
- package migration repair `d253daf8b7f6487d0a208b4d434f031a43b8ea4a`; and
- Docker mirror repair `2d046e52ae18a9b39ca17605b37d24948116451a`.

The final `tenant_scope`-default authority repair extends the same decision rather than creating another bounded context or ADR:

- static RED `c4861e6c4d063cb5a2deb1a680d909670a6d389b` requires migration 0009 to verify the exact `tenant_scope` default expression;
- executable PostgreSQL RED specimen `b9b39a361830880e1f88abc3b99735ea4daba37d` replaces the default with a test-only volatile function, proves that direct omitted-column insertion executes it, and requires the final verifier to reject the drift;
- causal package fix `83dc4c2d0d67c87b2769b2c71f5b097d8fbdbc89` adds the exact `pg_attrdef`/`pg_get_expr` check; and
- Docker mirror repair `38e0248e142ad543bab24e55f6bd8d4267a09b36` restores package/Docker byte identity.

Continuing runtime admission and dependency-identity lineage is also retained:

- runtime RED/repair lineage first extended `_require_rls_application_role()` to re-read the three canonical defaults after migration instead of transferring migration-time evidence to later connections;
- exact predecessor `18bd0319804373df4c1803d4753fd576de617dd1` supplied the realistic same-deparse/different-object dependency specimen and produced hosted PostgreSQL RED;
- causal production fix `df8c0450d6f1c0caa6464badbc452c5c298dbca0` adds the `pg_catalog.pg_depend` normal-dependency rejection to runtime default admission; and
- owner-contract RED `6d24afd2b02839e5b0473808768a72a5c52a1346` verifies that AGENTS/CLAUDE cannot regress to a deparse-only contract after the production guard exists.

This ADR remains Proposed until the current protected integration path executes the full hosted PostgreSQL/container acceptance and repository quality gates. A queued, pending, stale, predecessor, synthetic, or otherwise non-executed workflow is not GREEN evidence.

## Consequences

A restore or operator that intentionally changes any reviewed outbox default must reconcile the schema explicitly before the package will admit it. This may turn previously latent drift into an installation or runtime-admission failure, which is intentional: the package cannot treat unknown executable default authority as durable lifecycle truth.

The additional `pg_depend` read is part of admission cost and therefore part of complete buyer-path performance evidence. It must not be omitted from p95 measurement merely because it is a security catalog check.

The `tenant_scope` check protects the declared direct/operator compatibility surface without changing the package tenant-binding path. It does not imply that arbitrary direct SQL is authorized; AGENTS/CLAUDE continue to treat the custom tenant setting as a trusted application boundary rather than a credential.

The change does not add cross-service SQL, provider coupling, prompt/response storage, a mutable upstream dependency, or new publication authority. It narrows only the pg-llm-batch-owned lifecycle persistence boundary.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Default values*. https://www.postgresql.org/docs/18/ddl-default.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: INSERT*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: ALTER TABLE*. https://www.postgresql.org/docs/18/sql-altertable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_attrdef*. https://www.postgresql.org/docs/18/catalog-pg-attrdef.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_attribute*. https://www.postgresql.org/docs/18/catalog-pg-attribute.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_depend*. https://www.postgresql.org/docs/18/catalog-pg-depend.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html
