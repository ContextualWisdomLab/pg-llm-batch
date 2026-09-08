# Product and technical gap baseline

This document separates protected/shipped truth from active-PR evidence. Exact PR heads, checks, reviews, rulesets, security results, and releases must always be read live before merge or release decisions; this file is not a substitute for GitHub evidence.

## Product boundary

pg-llm-batch owns durable PostgreSQL-backed asynchronous LLM batch preparation, token/size accounting, provider-neutral `BatchInferencePort` lifecycle state, tenant/RLS enforcement, result ingestion, audit/provenance, and recovery. Model/provider discovery and routing remain contextual-orchestrator authority. Foreign product truth is consumed through released versioned contracts and anti-corruption layers; source copying, mutable-branch production dependencies, and cross-service application-table SQL are out of bounds.

## Protected-main truth

The protected integration branch is `main`. At the latest refresh it was `5913c4bad79d6bc29d7cc1c624abb7db2ea6a77c`. The package remains version `0.1.0`, and protected main still carries the Psycopg runtime graph. Therefore issue #322 remains an open commercial-policy defect at shipped/release authority even though the active #323 migration branch has advanced beyond that graph. No public release may claim the replacement is shipped until the pg8000 graph integrates normally into a protected exact head and the corresponding package/license/vulnerability/SBOM/provenance/reproducibility evidence passes on that same authority.

The repository has no immutable GitHub release at the latest refresh. A green Draft branch is not release authority: one exact protected head must pass the repository's applicable CI, security, coverage/docstring, package, migration/rollback/recovery, operability, SBOM/provenance, reproducibility, and review gates before version/tag/publication evidence is promoted.

## Active delivery lanes

PR #233 remains the dependency-root integration lane and must be judged from its live head and base. Its repository-local deterministic lanes have been green on the unchanged current head, while required central CodeQL/OpenCode/Noema settlement and a structurally satisfiable independent approval path remain non-passing owner prerequisites. Leaf churn, synthetic status, self-approval, and routine administrator bypass are not substitutes.

PR #323 is the active Draft migration lane for issue #322. It established `PostgresDriverPort`, retained the Psycopg implementation as a verification baseline, proved pg8000 1.31.5 behind the neutral port, and has now promoted the admitted pg8000 adapter into the branch's single centralized runtime selector. The branch manifest declares exact `pg8000==1.31.5` as the default runtime dependency; Psycopg 3.3.4 remains only in the `test` optional dependency and `dev` dependency group for legacy-baseline verification. The regenerated lock resolves pg8000 with `python-dateutil` and `scramp`/`asn1crypto` and no Psycopg dependency in the project default runtime edge.

The promotion preserves the existing candidate evidence: parameter binding, native no-parameter DB-API execution, tuple-row normalization, finite fetch budgets, exact/unknown row counts, transaction/context ownership, terminal connection state, thread-affine use, PostgreSQL RLS/session behavior, UUID/timestamp round-trip, SQLSTATE classification, cleanup precedence, JSONB adaptation, strict single-host URI/keyword conninfo parsing, explicit service-file resolution without ambient `PGSERVICEFILE` discovery, packaged restore-catalog acceptance, server-terminated-session recovery, exact dependency/license evidence, source-to-wheel Python payload parity, and package-installed execution outside the checkout across the supported Python matrix. Unsupported multi-host/socket/query/LDAP/ambient-service semantics remain fail closed rather than approximated.

The production construction boundary `load_pg8000_driver()` admits only exact pg8000 1.31.5, verifies the installed distribution identity and top-level import origin before package code executes, and optionally composes one caller-selected service file. The centralized `retained_postgres_driver()` now constructs that admitted adapter. This is a branch-level source/runtime fact, not protected-main or release authority.

### Runtime-graph RED and causal repair

The selector and `pyproject.toml` were promoted before the committed `uv.lock` had converged. Exact head `8972ec9a1f1e94ad40b5490be88e5e53d1dd200b` therefore produced a useful reality RED: frozen/default container installation still followed the stale lock and installed Psycopg rather than pg8000, while the production selector required pg8000. The PostgreSQL/container smoke failed through `retained_postgres_driver()` with the fixed unavailable-driver boundary, and the locked-dependency unit lane also failed before product tests. The failure was not a log-routing defect and did not justify a selector fallback or relaxed frozen install.

A bounded exact-head lock finalizer regenerated and verified the lock, proved that the project default runtime edge contains pg8000 and excludes Psycopg, ran `uv sync --locked --no-dev`, proved exact pg8000 1.31.5 is installed while Psycopg is absent from that production environment, constructed `Pg8000DriverAdapter` through the centralized selector, built the package, committed only `uv.lock`, and removed its own temporary workflow in the same descendant. Commit `e1045b6ed74e848cd99a50b02b42fe731fcc8b9b` is the resulting graph repair. Because that commit was authored by the workflow token, its automatically materialized pull-request CI/Release runs reported `action_required` without jobs; they are not GREEN evidence. A normal user-authored descendant must therefore re-run the full exact-head acceptance on the unchanged repaired graph.

## Highest-priority gaps

| Gap | Current state | Required next evidence |
| --- | --- | --- |
| Commercial PostgreSQL runtime dependency | P0 / active Draft | Re-prove the repaired pg8000 default graph on one exact current #323 head, then carry it through normal protected integration and immutable release evidence. |
| Production driver contract parity | Active / promoted on branch | Run real PostgreSQL/RLS/recovery/health/migration/package-installed acceptance through the production selector and fail closed on any pg8000 semantic mismatch. |
| Supply-chain admission | Active / strengthened | Bind exact pg8000 closure hashes, permissive-license evidence, vulnerability results, built package, SBOM, provenance, and reproducibility to the same final artifact/head. |
| Public commercial-license surface | Child lane #321 | Keep README/docs public wording conservative until #323's pg8000 graph is protected and accepted; then non-force restack #321 and update only its owned public files. |
| Dependency-root governance | External owner paths / non-passing | #233 still requires authenticated current-head central CodeQL/OpenCode/Noema settlement and a satisfiable independent approval path before normal protected integration. |
| Immutable product release | Not yet published | After the production dependency replacement and all gates pass on one integrated protected head, perform version/CHANGELOG/tag/package/SBOM/provenance/reproducibility/rollback publication and verify artifact identity. |
| Context Graph / EA projection | Candidate-only until released authority exists | Do not pin mutable producer heads. Continue pg-owned release-readiness seams and adopt only verified released contracts from canonical owners. |

## Commercial acceptance for issue #322

Completion requires all of the following on the final production graph, not only candidate fixtures:

- parameterized SQL and injection-safe bindings remain intact;
- commit, rollback, context-manager, cleanup-error precedence, cancellation/recovery, and connection lifecycle remain deterministic;
- tenant authority and transaction-local `set_config` behavior remain correct under forced RLS and restricted roles;
- JSON/JSONB, UUID, timestamp, row, row-count, and relevant PostgreSQL error semantics remain compatible;
- DSN parsing/rendering preserves the supported URI, keyword, and explicit-service-selector contract without credential leakage into argv or logs;
- concurrency, idempotency, checkpoint, schema application, logical restore, health, and finite-connect behavior pass realistic PostgreSQL tests through the production selector;
- the committed default runtime graph and built artifacts contain no disallowed GPL/LGPL/AGPL-family package;
- retained Psycopg verification dependencies remain outside production/default installation and release runtime evidence;
- package, license, vulnerability, SBOM, provenance, and reproducibility evidence bind the same immutable artifacts;
- the final unchanged protected head passes exact-source required checks and then-live review/ruleset requirements without self-approval or gate weakening.

## Context Fabric boundary

`context-graph-contracts` remains a contract-only Shared Kernel for canonical object/authority references, truth origin/status, bitemporal semantics, provenance, Context Assertion, and CloudEvents/schema/conformance/admission contracts. `enterprise-architecture-core` remains the EA Decision Plane. pg-llm-batch treats those repositories as foreign canonical owners and consumes only released contracts through explicit anti-corruption boundaries.

Prompt, response, batch-result, and user data remain pg/product-domain data and are not copied into EA authoritative architecture tables. Deployable service/API/worker/database/runtime/provider/version and lifecycle/risk/ownership/remediation changes may be projected only through a verified released Context Graph contract with provenance.

## Evidence discipline

Queued, pending, skipped-required, `action_required`, cancelled, absent, predecessor-head, model-only, and status-only evidence is non-passing. A current blocker is the next work item at its actual owner: pg-owned causes require a realistic RED, the smallest causal repair, focused/full GREEN, and exact-head refetch; foreign-owned causes require advancement of the existing owner path followed by independent pg work. A report, comment, handoff, or documentation-only change is never completion while executable code/test/release work remains.
