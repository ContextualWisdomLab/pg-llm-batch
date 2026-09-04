# Product and technical gap baseline

This document records shipped truth separately from active-PR evidence. Exact PR heads, checks, reviews, rulesets, and release identities must always be read live before merge or release decisions; this file is not a substitute for GitHub evidence.

## Product boundary

pg-llm-batch owns durable PostgreSQL-backed asynchronous LLM batch preparation, token/size accounting, provider-neutral `BatchInferencePort` lifecycle state, tenant/RLS enforcement, result ingestion, audit/provenance, and recovery. Model/provider discovery and routing remain contextual-orchestrator authority. Foreign product truth is consumed through released versioned contracts and anti-corruption layers; source copying, mutable-branch production dependencies, and cross-service application-table SQL are out of bounds.

## Protected-main truth

The protected integration branch is `main`. At the latest refresh it was `bdff1273d3885dedc5187632e1c8838b470c9b6d`. The package remains version `0.1.0`, and its production dependency graph still includes `psycopg[binary]>=3.1`. Therefore issue #322, replacement of the LGPL-family Psycopg runtime dependency, remains an open commercial-policy defect. No public release should claim that the current `pip install .` runtime graph is commercially clean while that defect remains.

The repository has no immutable GitHub release at the latest refresh. A release is not ready merely because a branch is green: one exact protected head must pass the repository's applicable CI, security, coverage/docstring, package, SBOM/provenance, reproducibility, migration/rollback/recovery, operability, and review gates before version/tag/publication evidence is promoted.

## Active delivery lanes

PR #233 remains the dependency-root delivery lane and must be judged from its live head and live base, not predecessor evidence.

PR #323 is the active Draft migration lane for issue #322. It establishes a driver-neutral PostgreSQL anti-corruption port, retains Psycopg only as the current baseline adapter, and evaluates pg8000 1.31.5 as candidate evidence without promoting it into the production manifest. The lane already exercises parameter binding, tuple-row normalization, row-count semantics, transaction and cleanup precedence, forced-RLS tenant scope, JSONB/UUID/timestamp behavior, exact candidate dependency hashes, and real PostgreSQL candidate smoke tests.

The current candidate supply-chain work also verifies license metadata for the exact five-wheel pg8000 candidate closure before installation. The verifier reads bounded wheel `METADATA` without importing candidate code, rejects GPL/LGPL/AGPL-family declarations, requires positive reviewed permissive-license evidence for every exact package/version, and rejects an unexpected wheel set. This strengthens candidate admission but does not itself approve a production driver replacement.

## Highest-priority gaps

| Gap | Current state | Required next evidence |
| --- | --- | --- |
| Commercial PostgreSQL runtime dependency | P0 / active | Complete issue #322: preserve shipped DB semantics while removing every disallowed GPL/LGPL/AGPL-family runtime package from the committed dependency graph. |
| Candidate driver contract parity | Active Draft | Close conninfo URI/keyword/service-selector compatibility, driver-level JSONB/error classification, concurrency/recovery, timeout/health, schema/restore, and package-installed behavior with realistic PostgreSQL evidence. |
| Candidate supply-chain admission | Active / strengthened | Exact wheel hashes and license metadata are now gated; complete vulnerability/SBOM/provenance and final runtime-graph evidence before promotion. |
| Exact-head CI execution | External control-plane dependency plus local continuation | Current required jobs must acquire a runner and check out the exact current head. Queued/pre-checkout evidence is non-passing; central `.github#712` owns the organization runner-admission diagnosis. |
| Immutable product release | Not yet published | After the production dependency replacement and all gates pass on one integrated protected head, perform version/CHANGELOG/tag/package/SBOM/provenance/reproducibility/rollback publication and verify artifact identity. |
| Context Graph / EA projection | Candidate-only until released authority exists | `context-graph-contracts` and `enterprise-architecture-core` currently expose no immutable GitHub release. Do not pin mutable producer heads. Continue pg-owned release-readiness seams and adopt only a verified released contract. |

## Commercial acceptance for issue #322

Completion requires all of the following on the final production graph, not only candidate fixtures:

- parameterized SQL and injection-safe bindings remain intact;
- commit, rollback, context-manager, cleanup-error precedence, cancellation/recovery, and connection lifecycle remain deterministic;
- tenant authority and transaction-local `set_config` behavior remain correct under forced RLS and restricted roles;
- JSON/JSONB, UUID, timestamp, row, row-count, and relevant PostgreSQL error semantics remain compatible;
- DSN parsing/rendering preserves the repository's supported URI, keyword, and service-selector contract without credential leakage into argv or logs;
- concurrency, idempotency, checkpoint, schema application, logical restore, health, and finite-connect behavior pass realistic PostgreSQL tests;
- the committed runtime graph and built artifacts contain no disallowed GPL/LGPL/AGPL-family package;
- package, license, vulnerability, SBOM, provenance, and reproducibility evidence bind the same immutable artifacts;
- the final unchanged head passes exact-source required checks and then-live review/ruleset requirements without self-approval or gate weakening.

## Context Fabric boundary

`context-graph-contracts` remains a contract-only Shared Kernel for canonical object/authority references, truth origin/status, bitemporal semantics, provenance, Context Assertion, and CloudEvents/schema/conformance/admission contracts. `enterprise-architecture-core` remains the EA Decision Plane. While their dedicated Context Fabric writer is active, pg-llm-batch treats both repositories as read-only source dependencies and advances their existing owner paths with exact consumer RED/GREEN criteria instead of creating competing writers.

Prompt, response, batch-result, and user data remain pg/product-domain data and are not copied into EA authoritative architecture tables. Deployable service/API/worker/database/runtime/provider/version and lifecycle/risk/ownership/remediation changes may be projected only through a verified released Context Graph contract with provenance.

## Evidence discipline

Queued, pending, skipped-required, cancelled, absent, predecessor-head, model-only, and status-only evidence is non-passing. A current blocker is the next work item at its actual owner: pg-owned causes require a realistic RED, the smallest causal repair, focused/full GREEN, and exact-head refetch; foreign-owned causes require advancement of the existing owner path followed by independent pg work. A report, comment, handoff, or documentation-only change is never completion while executable code/test/release work remains.
