# Lifecycle outbox privileged-view and materialized-copy authority

## Finding

The lifecycle outbox runtime admission already rejects direct `BYPASSRLS`/superuser identities and callable privileged `SECURITY DEFINER` routines, but that is not sufficient when the same runtime credential can `SELECT` a PostgreSQL view whose execution path eventually reaches the outbox under a privileged view owner. PostgreSQL 18 applies permissions and row-level-security policies for underlying relations using a view owner's rights by default. A view marked `security_invoker=true` instead uses the invoking principal's permissions and policies. This distinction creates an indirect tenant-boundary authority path even when the authenticated runtime login itself is `NOBYPASSRLS`.

The executable specimen added at RED commit `da5b109be87c126eb618922c274bb858b57d7b71` creates two lifecycle rows for different tenants, proves the ordinary runtime caller sees one row through the forced-RLS base table, and proves the same caller sees both rows through a directly outbox-dependent, caller-selectable view owned by a separate `BYPASSRLS` role. The package call on the pre-repair authority model would therefore have admitted a credential that retained a usable cross-tenant read capability outside the package-authored SQL path.

A second fresh review found the direct-view repair incomplete. RED commit `5e38538395e28b1c02bcb15129225576d8e1e414` adds an outer view owned by an ordinary `NOBYPASSRLS` role. The runtime caller can select only that outer view. Its owner can select a hidden inner view owned by the `BYPASSRLS` principal, and the inner view directly reads the outbox. The runtime caller has no direct `SELECT` on the inner view, yet selecting the outer view still returns both tenants. A direct caller-to-leaf predicate therefore misses a real nested view authority path.

A third review found a distinct copied-data escape. PostgreSQL materialized views persist the result of their defining query and later return rows directly from the materialized relation; the defining rule is used to populate or refresh the copy, not to re-evaluate the source relation when the runtime caller reads it. A materialized view populated under `BYPASSRLS` authority can therefore contain rows from multiple outbox tenants. Giving a normal `NOBYPASSRLS` runtime login `SELECT` on that materialized copy exposes those stored rows without consulting the outbox's live forced-RLS policy. The same capability can be hidden behind an ordinary outer view even when the runtime login has no direct `SELECT` on the materialized relation.

RED commits `f78bbcec2f18538b0df988bfdc9f678727d3a922`, `133cbd226eddb31a73e3b8ff51f86bac18e0a595`, and `cfe3d13e6ca929e8c40e501f6ccd35541e27c064` add a dedicated PostgreSQL specimen, wire it into the hosted container lane, and require a static catalog contract. The specimen creates one tenant-a and one tenant-b outbox row, materializes both while executing as a separate `BYPASSRLS` owner, proves the runtime caller sees one row through the forced-RLS base relation but two through the materialized copy, then repeats the escape through an outer ordinary view whose owner alone can select the hidden materialized relation. Revoking every caller-reachable read path is the positive control.

## Decision

Production repair `31f037ea0f4781f2c39020e78248a0c94c7eb969` originally kept runtime admission in the existing single catalog round trip and extended the selectable-role authority envelope with a cycle-safe catalog proof over `pg_class`, `pg_namespace`, `pg_rewrite`, and `pg_depend` for ordinary views.

Materialized-copy repair `9c3a4ab99c0c8a02db4600a097647eb8b47fac4d` generalizes that proof to a `reachable_relation(relation_oid, caller_oid)` read graph containing ordinary views and materialized views. The graph starts from every non-system view or materialized view that a selectable runtime principal can actually read. Only ordinary views are traversed at read time: PostgreSQL expands their rewrite rules when queried, and each edge carries the effective principal dictated by `security_invoker=true` versus owner-rights execution. A materialized relation terminates the live read graph because selecting it returns stored rows rather than executing its defining query.

A separate cycle-safe `materialized_source(materialized_oid, source_oid)` provenance closure follows the stored definition of each reachable materialized view through nested ordinary or materialized relations. Admission rejects any reachable materialized relation whose definition graph reaches `public.llm_context_lifecycle_outbox`. It does not attempt to infer safety from mutable copied row contents, a tenant literal in SQL text, the current materialized-view owner, or the authority used by the most recent refresh. Those facts are not a durable live-RLS guarantee. A materialized outbox copy is outside the supported runtime credential envelope until its read path is removed from that credential.

For ordinary views, the earlier rule remains unchanged: admission rejects any reachable non-`security_invoker` view that directly depends on the outbox when its owner is `SUPERUSER`/`BYPASSRLS` and can read the outbox. The implementation does not parse mutable view SQL text, mutate ownership or ACLs, drop relations, weaken forced RLS, or add another database round trip.

Static contract repair `960cb78d6925829f14dec3c70590fc74468c81b1` updates the ordinary-view assertions to the generalized relation graph and preserves the materialized-source closure explicitly. Hosted exact-head evidence is required before this repair is considered GREEN; a queued or predecessor run is not transferred.

## Security effect

A runtime DSN is treated as an authority-bearing credential, not merely as a path used by package-authored SQL. If that credential can traverse one or more ordinary views and eventually cause PostgreSQL to evaluate the outbox under a `BYPASSRLS` or superuser owner, or can directly or indirectly read a materialized relation whose stored definition derives from the outbox, the credential is outside the supported tenant-scoped append-only boundary even when every package-authored query remains tenant-qualified. The guard therefore fails before `pg_llm_batch.tenant_scope` is bound or durable outbox rows are read or written.

The materialized-view rule is intentionally provenance-based rather than content-based. PostgreSQL documents materialized views as persistent table-like results and documents `REFRESH MATERIALIZED VIEW` as replacing their stored contents by executing the backing query. A successful base-table RLS check at runtime cannot establish which authority populated older materialized rows, so admission must not treat a copied outbox projection as if it remained under live RLS.

## Verification boundary

The final claim requires exact-head hosted PostgreSQL/container execution of the direct and nested ordinary-view specimens, the direct and hidden materialized-copy specimens, plus the existing Python 3.10/3.12/3.14, 100% owned-production statement/branch coverage, 100% public-docstring, lint/package, and Release Acceptance gates. The realistic capacity envelope in issue #307 must include both recursive catalog closures rather than timing only tenant data SQL. A queued, cancelled, stale-base, or predecessor run is not GREEN evidence.

## References

PostgreSQL Global Development Group. (2026). *CREATE POLICY*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026). *CREATE VIEW*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createview.html

PostgreSQL Global Development Group. (2026). *Materialized views*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/rules-materializedviews.html

PostgreSQL Global Development Group. (2026). *REFRESH MATERIALIZED VIEW*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-refreshmaterializedview.html

PostgreSQL Global Development Group. (2026). *Rules and privileges*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/rules-privileges.html

PostgreSQL Global Development Group. (2026). *CREATE ROLE*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createrole.html
