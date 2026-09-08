# Product and technical gap baseline

This document records shipped truth separately from active-PR evidence. Exact PR heads, checks, reviews, rulesets, and release identities must always be read live before merge or release decisions; this file is not a substitute for GitHub evidence.

## Product boundary

pg-llm-batch owns durable PostgreSQL-backed asynchronous LLM batch preparation, token/size accounting, provider-neutral `BatchInferencePort` lifecycle state, tenant/RLS enforcement, result ingestion, audit/provenance, and recovery. Model/provider discovery and routing remain contextual-orchestrator authority. Foreign product truth is consumed through released versioned contracts and anti-corruption layers; source copying, mutable-branch production dependencies, and cross-service application-table SQL are out of bounds.

## Protected-main truth

The protected integration branch is `main`. At the latest refresh it was `5913c4bad79d6bc29d7cc1c624abb7db2ea6a77c`. The package remains version `0.1.0`, and its production dependency graph still includes `psycopg[binary]>=3.1`. Therefore issue #322, replacement of the LGPL-family Psycopg runtime dependency, remains an open commercial-policy defect. No public release should claim that the current `pip install .` runtime graph is commercially clean while that defect remains.

The repository has no immutable GitHub release at the latest refresh. A release is not ready merely because a branch is green: one exact protected head must pass the repository's applicable CI, security, coverage/docstring, package, SBOM/provenance, reproducibility, migration/rollback/recovery, operability, and review gates before version/tag/publication evidence is promoted.

## Active delivery lanes

PR #233 remains the dependency-root delivery lane and must be judged from its live head and live base, not predecessor evidence.

PR #323 is the active Draft migration lane for issue #322. It establishes a driver-neutral PostgreSQL anti-corruption port, retains Psycopg only as the current baseline adapter, and evaluates pg8000 1.31.5 as candidate evidence without promoting it into the production manifest. The lane exercises parameter binding, tuple-row normalization, row-count semantics, transaction and cleanup precedence, forced-RLS tenant scope, JSONB/UUID/timestamp behavior, exact candidate dependency hashes and license metadata, URI/keyword/explicit-service selection, packaged restore-catalog acceptance, thread-affinity rejection at the anti-corruption boundary, and real PostgreSQL candidate execution. Exact branch evidence now also terminates a live candidate backend from a second authenticated session, requires the severed capability to fail and become terminal, and proves recovery only by opening a fresh connection. That is candidate recovery evidence; it is not production-driver promotion.

Candidate supply-chain admission now verifies both the exact five-wheel pg8000 closure and the published pg8000 1.31.5 source distribution before candidate installation. CI pins the wheel and source-distribution SHA-256 digests, reads bounded wheel `METADATA` without importing candidate code, rejects GPL/LGPL/AGPL-family declarations, requires positive reviewed permissive-license evidence for every exact package/version, and compares every Python source path and byte digest under the pg8000 package between the pinned source distribution and universal wheel. The parity verifier does not extract archives, import candidate code, follow archive links, or execute a source build. This closes the published source-to-wheel executable-payload parity gap for the selected candidate artifacts; it does not itself approve a production driver replacement or provide an upstream build attestation.

## Highest-priority gaps

| Gap | Current state | Required next evidence |
| --- | --- | --- |
| Commercial PostgreSQL runtime dependency | P0 / active | Complete issue #322: preserve shipped DB semantics while removing every disallowed GPL/LGPL/AGPL-family runtime package from the committed dependency graph. |
| Candidate driver contract parity | Active Draft | Real server-terminated-session discard and fresh-session recovery are now proven on the candidate. Close remaining selector/conninfo compatibility, realistic concurrency beyond the deterministic anti-cross-thread guard, timeout/health, remaining schema/recovery surfaces, and package-installed behavior before production promotion. |
| Candidate supply-chain admission | Active / strengthened | Exact wheel/source hashes, source-to-wheel Python payload parity, and closure license metadata are gated; complete vulnerability/SBOM/provenance and final runtime-graph evidence before promotion. |
| Dependency-root governance | External owner paths / non-passing | #233 has leaf CI/release/security evidence but still requires authenticated current-head compatibility CodeQL/OpenCode/Noema settlement and a structurally satisfiable independent approval path before normal protected integration. |
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
