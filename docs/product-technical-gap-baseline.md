# Product and technical gap baseline

This document separates protected/shipped truth from active-PR evidence. Exact PR heads, checks, reviews, rulesets, security results, and releases must always be read live before merge or release decisions; this file is not a substitute for GitHub evidence.

## Product boundary

pg-llm-batch owns durable PostgreSQL-backed asynchronous LLM batch preparation, token/size accounting, provider-neutral `BatchInferencePort` lifecycle state, tenant/RLS enforcement, result ingestion, audit/provenance, and recovery. Model/provider discovery and routing remain contextual-orchestrator authority. Foreign product truth is consumed through released versioned contracts and anti-corruption layers; source copying, mutable-branch production dependencies, and cross-service application-table SQL are out of bounds.

## Protected-main truth

The protected integration branch is `main`. At the latest refresh it was `5913c4bad79d6bc29d7cc1c624abb7db2ea6a77c`. The package remains version `0.1.0`, and protected main still carries the Psycopg runtime graph. Therefore issue #322 remains an open commercial-policy defect at shipped/release authority even though the active #323 migration branch has advanced beyond that graph. No public release may claim the replacement is shipped until the pg8000 graph integrates normally into a protected exact head and the corresponding package/license/vulnerability/SBOM/provenance/reproducibility evidence passes on that same authority.

The repository has no immutable GitHub release at the latest refresh. A green Draft branch is not release authority: one exact protected head must pass the repository's applicable CI, security, coverage/docstring, package, migration/rollback/recovery, operability, SBOM/provenance, reproducibility, and review gates before version/tag/publication evidence is promoted.

## Active delivery lanes

PR #233 remains the dependency-root integration lane and must be judged from its live head and base. Its repository-local deterministic lanes remain green on exact `01d231fde23b82e2ced258d7bfcb4721ed75706d`, while required compatibility CodeQL, OpenCode, Noema, and a structurally satisfiable independent approval path remain non-passing owner prerequisites. The current canonical central CodeQL repair is `.github#2040` at exact `6706c231ab06a3c91c43fdb5b989cfcd79fff593`; its Security Scan, Semgrep, Python Security, and Agent Review Runtime Quality runs are successful but CodeQL PR `34251822255` is terminal failure. Leaf churn, synthetic status, self-approval, and routine administrator bypass are not substitutes. pg-llm-batch must consume only protected central behavior and must not copy mutable central workflow source locally.

PR #323 is the active Draft migration lane for issue #322. It established `PostgresDriverPort`, retained the Psycopg implementation as a verification baseline, proved pg8000 1.31.5 behind the neutral port, and has now promoted the admitted pg8000 adapter into the branch's single centralized runtime selector. The branch manifest declares exact `pg8000==1.31.5` as the default runtime dependency; Psycopg 3.3.4 remains only in the `test` optional dependency and `dev` dependency group for legacy-baseline verification. The regenerated lock resolves pg8000 with `python-dateutil` and `scramp`/`asn1crypto` and no Psycopg dependency in the project default runtime edge.

The promotion preserves the existing candidate evidence: parameter binding, native no-parameter DB-API execution, tuple-row normalization, finite fetch budgets, exact/unknown row counts, transaction/context ownership, terminal connection state, thread-affine use, PostgreSQL RLS/session behavior, UUID/timestamp round-trip, SQLSTATE classification, cleanup precedence, JSONB adaptation, strict single-host URI/keyword conninfo parsing, explicit service-file resolution without ambient `PGSERVICEFILE` discovery, packaged restore-catalog acceptance, server-terminated-session recovery, exact dependency/license evidence, source-to-wheel Python payload parity, and package-installed execution outside the checkout across the supported Python matrix. Unsupported multi-host/socket/query/LDAP/ambient-service semantics remain fail closed rather than approximated.

The production construction boundary `load_pg8000_driver()` admits only exact pg8000 1.31.5, verifies the installed distribution identity and top-level import origin before package code executes, and optionally composes one caller-selected service file. The centralized `retained_postgres_driver()` now constructs that admitted adapter. This is a branch-level source/runtime fact, not protected-main or release authority. The candidate driver-port module deliberately does not import pg8000 itself; the runtime loader injects the admitted DB-API module. pg8000 is nevertheless a pinned production dependency on this migration branch, so issue #322 remains open because protected integration and immutable-release evidence are incomplete, not because pg8000 is absent from the production graph.

### Runtime-graph RED and causal repair

The selector and `pyproject.toml` were promoted before the committed `uv.lock` had converged. Exact head `8972ec9a1f1e94ad40b5490be88e5e53d1dd200b` therefore produced a useful reality RED: frozen/default container installation still followed the stale lock and installed Psycopg rather than pg8000, while the production selector required pg8000. The PostgreSQL/container smoke failed through `retained_postgres_driver()` with the fixed unavailable-driver boundary, and the locked-dependency unit lane also failed before product tests. The failure was not a log-routing defect and did not justify a selector fallback or relaxed frozen install.

A bounded exact-head lock finalizer regenerated and verified the lock, proved that the project default runtime edge contains pg8000 and excludes Psycopg, ran `uv sync --locked --no-dev`, proved exact pg8000 1.31.5 is installed while Psycopg is absent from that production environment, constructed `Pg8000DriverAdapter` through the centralized selector, built the package, committed only `uv.lock`, and removed its own temporary workflow in the same descendant. Commit `e1045b6ed74e848cd99a50b02b42fe731fcc8b9b` is the resulting graph repair. Because that commit was authored by the workflow token, its automatically materialized pull-request CI/Release runs reported `action_required` without jobs; they are not GREEN evidence.

The later production-promotion RED at `3e0103fcf0a94327828b62137666f52fa12b6561` then exposed three post-cutover defects: the CLI confidentiality classifier had become coupled to pg8000's intentionally narrower connection grammar, a workflow contract still asserted the pre-promotion dependency state, and the packaged restore smoke directly imported removed Psycopg. Minimal causal repair `2afd5be12847b51c8d476c59f5b328c697069780` separated argv confidentiality from concrete-driver connectability, updated the production dependency assertion, and routed restore acceptance through `retained_postgres_driver()`.

That repair stayed intact through ordinary descendants. Exact #323 head `c83cbcee04a49771cce7b1b1575bcf3d54bf0af3` reached CI `34259353013` and Release Acceptance `34259353130` terminal success. All seven CI jobs succeeded: Python 3.10/3.11/3.12/3.13/3.14, coverage/docstrings/lint/package, and the container/PostgreSQL runtime-smoke lane. The container lane re-verified exact pg8000 dependency/source digests and permissive-license evidence, release-Python installation, and real PostgreSQL pg8000 smokes on Python 3.10/3.12/3.14. This proves the Draft branch's exact source at that head, not protected integration or immutable release.

### Service-file authority RED and causal repair

The explicit service-file resolver originally validated only the descriptor obtained after `os.open()`. A caller-selected final symlink, or a pathname substitution between selection and open, could therefore redirect the supposedly explicit `pg_service.conf` capability to another regular file and change database host/user/database/password authority without failing admission. This is a connection-authority defect even though ambient `PGSERVICEFILE` discovery remains disabled.

Real final-symlink and deterministic path-substitution regressions were introduced at `86892562f37c59bf54c2d708e4bae8d61dd6b032` and `89757e4396b796a1dd620b9bbba111f80d86a3ae`. Subsequent descendant pushes cancelled their hosted runs before terminal test execution, so those commits are test-first source evidence rather than falsely reported hosted RED. Minimal production repair `63ef822c2b48cf4ff2d9dddcf8641ba0ca652ff3` now performs `lstat()` on the caller-selected final component, requires that component itself to be a regular file, retains its `(st_dev, st_ino)` identity, opens the file, and requires the descriptor's `fstat()` identity to match before reading. The existing bounded byte budget, regular-file check, before/after metadata stability, strict UTF-8 decoding, and generic non-content-bearing errors remain intact.

Exact `63ef822...` then produced a separate quality RED in CI `34267147130`: all functional/unit/Python/container behavior passed, but the 100% owned-production coverage gate found the newly added `os.open()` failure normalization unexercised. Commit `251cdec97c95f2e842b0fcbeacdd43cd86395c0d` added the focused preflight-open-failure regression without changing production behavior. Exact CI `34267560647` and Release Acceptance `34267560557` both completed successfully. The quality lane reported `1652 passed, 5 deselected`, public docstrings 100%, and production coverage exactly 100% across 4,639 statements and 1,320 branches with zero misses/partials.

A later authority review found a second, independent indirection: the resolver retained a relative `Path` object unchanged. Constructing it under one working directory and changing the process working directory before resolution therefore redirected the same `pg_service.conf` selector to a different file without tripping the final-component inode check. Exact test-first head `3efb40078efeb64ea28bebaf28b2795265c04d1f` reproduced that behavior; CI `34272808960` reached real unit-test failures on the exact source while Release Acceptance `34272809031` independently succeeded. Minimal production repair `2077809188cbc0f0dd8bb7f2f11af859b4ad15ed` binds the caller's relative path to an absolute construction-time path before later working-directory changes can affect resolution. It does not add ambient service-file discovery or broaden the accepted connection parameter grammar. The current documentation descendant must reacquire its own exact-head CI/Release evidence; predecessor GREEN is not transferred.

### Public-surface descendant RED and repair

PR #321 owns only `README.md` and `docs/index.md` relative to #323. After it was reconciled onto exact parent `c83cbcee04a49771cce7b1b1575bcf3d54bf0af3`, child head `d546f6d8106cbf41bf5d72fa8e595363c4e7febe` exposed a real documentation RED in CI `34260943035`: five current-parent operator/security contracts had been dropped from README while production coverage and public-docstring gates remained satisfied.

Minimum causal repair `224ed124b675eaf0ec1f558a458286610387500b` changed only README versus that RED head. It restored the explicit 1 MiB `count-tokens` stdin limit, canonical retirement wording for the old SQL provider retriever, the closed transient GET retry-status set, the `source_superusers_trusted` logical-restore trust/rollback boundary, and explicit non-retry rules for TLS handshake/certificate and fingerprint failures. Exact-head CI `34262344110` and Release Acceptance `34262344236` then completed successfully. #321 remains Draft because parent integration, qualifying approval, central required checks, and immutable release authority remain unsatisfied. Since #323 has moved again for the service-file authority repair, #321 must be non-force reconciled onto the final current parent before its prior GREEN can be treated as current child evidence.

### Transport-security boundary remains separate

Issue #322 is a dependency-license migration and does not close PostgreSQL transport-security issue #123. The current #323 adapter does not yet establish a package-wide mandatory verified remote-TLS/server-identity policy, so its successful PostgreSQL smokes are not evidence that remote transport encryption or server identity is mandatory. PostgreSQL 18 recommends `verify-full` in security-sensitive environments because it requires encryption, CA validation, and hostname matching.

Issue #123 remains the canonical owner for the package-wide transport policy. Its acceptance must cover package-created remote TCP connections, deliberate local/embedding-host exceptions, trusted CA/hostname success, wrong CA and hostname mismatch, downgrade/plaintext refusal, recovery, and caller-owned connection authority. #323 and #321 must not race that broad policy or describe the driver migration as TLS/server-identity completion.

## Highest-priority gaps

| Gap | Current state | Required next evidence |
| --- | --- | --- |
| Commercial PostgreSQL runtime dependency | P0 / active Draft / exact predecessor GREEN observed | Preserve the proven pg8000 default graph through exact-head revalidation of current documentation descendants, normal prerequisite integration, non-force child reconciliation, one unchanged final #323 head, protected merge, and immutable release evidence. |
| PostgreSQL transport encryption / server identity | P0 security / canonical issue #123 | Complete the existing owner lane with realistic TLS-enabled PostgreSQL acceptance, explicit downgrade refusal and server-identity verification; do not infer this from #322 or a successful pg8000 connection. |
| Explicit service-file authority | Active / repaired on #323 | Preserve final-component inode retention, construction-time binding of relative paths, bounded parsing, and fixed diagnostics through final exact-head CI, package-installed/runtime acceptance, protected integration, and release. Parent-directory race hardening remains separate unless a realistic authority-changing RED proves it necessary. |
| Production driver contract parity | Active / promoted on branch | Preserve real PostgreSQL/RLS/recovery/health/migration/package-installed acceptance through the production selector and fail closed on any newly proven pg8000 semantic mismatch. |
| Supply-chain admission | Active / strengthened | Bind exact pg8000 closure hashes, permissive-license evidence, vulnerability results, built package, SBOM, provenance, and reproducibility to the same final artifact/head. |
| Public commercial-license surface | Child lane #321 / stale after parent movement | Preserve its two-file semantic delta with ordinary non-force reconciliation onto the final #323 head; reacquire exact child CI/Release and do not present it as shipped until protected release evidence exists. |
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
- explicit service-file capability selection cannot be redirected by a final-component symlink, a different inode substituted before open, or a later working-directory change after a relative path has been selected;
- concurrency, idempotency, checkpoint, schema application, logical restore, health, and finite-connect behavior pass realistic PostgreSQL tests through the production selector;
- the committed default runtime graph and built artifacts contain no disallowed GPL/LGPL/AGPL-family package;
- retained Psycopg verification dependencies remain outside production/default installation and release runtime evidence;
- package, license, vulnerability, SBOM, provenance, and reproducibility evidence bind the same immutable artifacts;
- the final unchanged protected head passes exact-source required checks and then-live review/ruleset requirements without self-approval or gate weakening; and
- issue #322 completion is not represented as transport-security completion: remote TLS/server-identity policy remains issue #123 authority until that separate acceptance is integrated and released.

## Context Fabric boundary

`context-graph-contracts` remains a contract-only Shared Kernel for canonical object/authority references, truth origin/status, bitemporal semantics, provenance, Context Assertion, and CloudEvents/schema/conformance/admission contracts. `enterprise-architecture-core` remains the EA Decision Plane. pg-llm-batch treats those repositories as foreign canonical owners and consumes only released contracts through explicit anti-corruption boundaries.

Prompt, response, batch-result, and user data remain pg/product-domain data and are not copied into EA authoritative architecture tables. Deployable service/API/worker/database/runtime/provider/version and lifecycle/risk/ownership/remediation changes may be projected only through a verified released Context Graph contract with provenance.

## Evidence discipline

Queued, pending, skipped-required, `action_required`, cancelled, absent, predecessor-head, model-only, and status-only evidence is non-passing. A current blocker is the next work item at its actual owner: pg-owned causes require a realistic RED, the smallest causal repair, focused/full GREEN, and exact-head refetch; foreign-owned causes require advancement of the existing owner path followed by independent pg work. A report, comment, handoff, or documentation-only change is never completion while executable code/test/release work remains.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: SSL support*. https://www.postgresql.org/docs/18/libpq-ssl.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: The connection service file*. https://www.postgresql.org/docs/18/libpq-pgservice.html

Locke, T. (2025). *pg8000 1.31.5: Python interface to PostgreSQL*. PyPI. https://pypi.org/project/pg8000/1.31.5/
