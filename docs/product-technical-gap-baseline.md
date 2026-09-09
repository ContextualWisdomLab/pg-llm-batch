# Product and technical gap baseline

This baseline records durable product and technical truth. Mutable PR heads, child heads, reviews, checks, rulesets, and release state must be read live before merge or release decisions; recording a mutable descendant SHA inside its parent would change the parent and immediately invalidate the recorded ancestry.

## Product boundary

pg-llm-batch owns PostgreSQL-backed durable/asynchronous LLM batch preparation and execution records, token/size accounting, lifecycle state, tenant/RLS enforcement, result ingestion, audit/provenance, recovery, and the provider-neutral `BatchInferencePort` plus PostgreSQL driver boundary required to support those capabilities.

Provider/model discovery and routing remain contextual-orchestrator authority. Foreign domain truth is consumed only through released versioned contracts and explicit anti-corruption layers. Source copying, mutable-branch production dependencies, provider-group hard-coding, and cross-service application-table SQL are outside this bounded context.

Commercial PostgreSQL-driver replacement does not transfer transport-security authority into the license migration. Package-wide remote TLS, trusted-CA/hostname verification, downgrade/plaintext refusal, server SSL refusal, and caller-owned connection-policy acceptance remain issue #123 authority.

## Protected/shipped truth

At this refresh protected `main` remains `5913c4bad79d6bc29d7cc1c624abb7db2ea6a77c`, version `0.1.0`, with the Psycopg production runtime graph. Issue #322 therefore remains an open shipped/release defect even though Draft #323 carries the replacement graph and stronger evidence.

A GREEN Draft is not protected or released authority. No commercial completion claim is valid until one normally integrated protected head binds version, CHANGELOG, tag, package, license, vulnerability, SBOM, provenance, reproducibility, migration/recovery, rollback, review, and then-live required-check evidence to an immutable release.

## Active delivery lanes

### Dependency root: PR #233

PR #233 is the earliest protected-integration prerequisite. Its repository-local deterministic lanes are GREEN, while required compatibility CodeQL, OpenCode, Noema, and a qualifying independent approval remain non-passing. The canonical CodeQL repair is owned by the central `.github` repository. pg-llm-batch must consume protected central workflow behavior rather than copy mutable central workflow source or weaken leaf gates.

### Commercial PostgreSQL driver: PR #323

PR #323 owns issue #322's active migration. The branch pins production `pg8000==1.31.5`, keeps Psycopg only as optional test/development verification, and selects the admitted implementation through `PostgresDriverPort` / `retained_postgres_driver()`.

`load_pg8000_driver()` admits only the exact pg8000 version, checks installed-distribution identity and import origin before package code executes, and optionally composes one caller-selected service file. Unsupported multi-host/socket/query/LDAP/ambient-service semantics remain fail closed rather than being approximated.

The branch preserves realistic PostgreSQL acceptance for parameter binding, no-parameter DB-API execution, row normalization and exact/unknown row counts, transaction/context ownership, cleanup precedence, terminal connection state, thread-affine use, tenant/RLS/session behavior, UUID/timestamp and JSONB adaptation, SQLSTATE classification, checkpoint/recovery, schema/restore behavior, package-installed execution, and supported-Python runtime smokes.

The production-like no-dev graph and component image also preserve exact dependency/source digests, positive license admission, CycloneDX SBOM policy, source-wheel parity, removal of superseded `libpq5`, and removal of inherited Python 3.14 pip/setuptools/wheel installation authority while still constructing the admitted pg8000 driver.

### Public commercial surface: PR #321

PR #321 owns only `README.md` and `docs/index.md` relative to #323. Its exact head, merge base, checks, and review state are intentionally not pinned here. Every run must read the child live, require its merge base to equal the then-current #323 head, require only those two relative paths, advance it through ordinary non-force ancestry, and reacquire exact-child acceptance after every parent movement. Parent/predecessor GREEN is ancestry evidence only.

## Runtime-graph RED and causal repair

The selector and manifest were promoted before the committed lock converged. Exact `8972ec9a1f1e94ad40b5490be88e5e53d1dd200b` therefore demonstrated that frozen/default installation could still install Psycopg while the production selector required pg8000. `e1045b6ed74e848cd99a50b02b42fe731fcc8b9b` regenerated the lock and proved the default graph contains pg8000 and excludes Psycopg.

A later production-promotion RED at `3e0103fcf0a94327828b62137666f52fa12b6561` exposed three post-cutover defects: CLI confidentiality had become coupled to the narrower concrete-driver grammar, a workflow contract still asserted the pre-promotion dependency state, and packaged restore smoke imported removed Psycopg. Minimal repair `2afd5be12847b51c8d476c59f5b328c697069780` separated argv-secret classification from concrete-driver connectability, updated the dependency contract, and routed restore acceptance through `retained_postgres_driver()`.

## Explicit service-file authority RED and repair

The explicit `pg_service.conf` capability is caller-selected and bounded. It does not perform ambient `PGSERVICEFILE`, user/system service-file, LDAP, or filesystem search discovery. Four independent authority defects have been repaired.

First, final-component symlink/path substitution during a read could redirect the selected file. `63ef822c2b48cf4ff2d9dddcf8641ba0ca652ff3` added regular non-symlink selection, descriptor authentication, bounded reads, before/after metadata stability, strict UTF-8/NUL rejection, and generic non-content-bearing diagnostics. The new error-normalization branches were then covered to restore the 100% production gate.

Second, retaining a relative path allowed a later `chdir()` to change the selector. Test-first `3efb40078efeb64ea28bebaf28b2795265c04d1f` produced a real CI RED; `2077809188cbc0f0dd8bb7f2f11af859b4ad15ed` binds a relative selection to its construction-time absolute path.

Third, absolute binding still left the selected parent pathname replaceable. Test-first `a7bb3ea76ad9747b83f517d518b2ddf22fdd7e92` reproduced parent replacement. `3dc5dad088ff8732d9e3b9a715f2f6e7e467e862` retains the construction-time parent `(st_dev, st_ino)`, authenticates the reopened directory descriptor, and performs final-component operations relative to that descriptor.

Fourth, parent identity plus per-read final identity still did not retain the selected regular-file identity across resolver construction and later resolution. A same-parent atomic replacement could therefore point the same filename at a new regular inode while each later `lstat()`/`open()`/`fstat()` sequence remained internally consistent. Test-first `491e9dc9349a816e37e015c8752e81b973c1ab95` reproduced this behavior: completed coverage job `102297319938` failed `test_candidate_service_file_rejects_selected_inode_replacement` because no `Pg8000CandidateInvalidConninfoError` was raised (`1 failed, 1660 passed, 5 deselected`). The overall CI run was subsequently cancelled by the immediate descendant, so the already-completed failing job is the RED evidence rather than the cancelled workflow conclusion.

Minimal source repair `71922a5ed1231049e235e165490f514fd53c9f6a` captures the selected final regular-file `(st_dev, st_ino)` at resolver construction, after authenticating the retained parent. Every later resolution must match that retained selected-file identity both before open and on the opened descriptor. Replacing the pathname with a different regular file therefore requires constructing a new resolver rather than silently changing retained database connection authority.

That required production signature exposed one stale private-helper test in CI `34297602591`: `test_service_file_preserves_primary_failure_when_close_also_fails` called `_read_bounded_utf8()` without the new selected-identity argument. Ordinary descendant `57d1abb9570fbb8605dd6abfe0ed537cf297216d` updates only that test call; the production identity remains mandatory. Exact `57d1abb...` reacquired CI `34297749787` and Release Acceptance `34297749879`, both terminal success, before this documentation descendant.

These filesystem controls prove selector authority, not remote TLS/CA/hostname policy. Issue #123 remains separate.

## Production SBOM RED and causal repair

Issue #322 requires the final default graph, package, and SBOM to exclude disallowed GPL/LGPL/AGPL-family dependencies. The branch generates CycloneDX evidence from the production-like no-dev environment after installing the exact package and hash-verified pg8000 closure, fails closed if pg-llm-batch or pg8000 is absent, if Psycopg appears, or if GPL/LGPL/AGPL-family license evidence appears, and preserves the validated SBOM as evidence.

The first production workflow configuration used a bare Syft version and produced a real HTTP-404 CI RED before Syft executed. Primary inspection of the pinned action showed that its installer URL uses the supplied value as a git ref and expects the v-prefixed release tag. The contract was corrected first, then `bc774185a4ba3fcbebe924aa1051154c3a713339` changed the production value to `v1.51.1`. Exact repair CI completed SBOM generation, policy validation, artifact preservation, PostgreSQL startup/health, and pg8000 smokes.

This is Draft evidence only until bound to an immutable protected release.

## Component-runtime minimization

After pg8000 became the production graph, the component image still installed `libpq5`. Test-first acceptance made that stale native dependency a RED; the repair removed it, retained the health-check dependency, and added final-image proof that `libpq5` is absent while the copied no-dev environment can construct `retained_postgres_driver()`.

The image had also moved to Python 3.14 while cleanup still targeted Python 3.11 packaging tools. The corrected runtime removes Python 3.14 pip/setuptools/wheel installation authority and fails image construction if `pip`, `pip3`, or `pip3.14` remains discoverable. These changes reduce mutable installation surface but are not a complete container-hardening claim.

## Transport-security boundary

Issue #322 does not close issue #123. Successful pg8000 connections, explicit service-file inode/parent/path authority, production SBOM policy, no-`libpq5`, and no-runtime-pip evidence do not prove mandatory verified remote TLS or authenticated server identity.

Issue #123 remains canonical for package-created remote TCP connections, deliberate local/embedding-host exceptions, trusted CA plus matching hostname, wrong-CA and hostname-mismatch rejection, plaintext/downgrade refusal, server SSL refusal, restart/recovery, bounded diagnostics, and caller-owned connection non-interference.

## Highest-priority gaps

| Gap | Current state | Required next evidence |
| --- | --- | --- |
| Commercial PostgreSQL runtime dependency | P0 / active Draft | Preserve the pg8000 default graph through normal prerequisite integration, obtain one unchanged final #323 head, merge normally, then bind immutable protected-release evidence. |
| Explicit service-file authority | Repaired on #323 | Preserve construction-time absolute path, parent identity, selected regular-file identity, descriptor-relative I/O, bounded parsing, and generic diagnostics through final integration/release. |
| Production runtime SBOM | Active / Draft evidence | Carry validated CycloneDX evidence through protected integration and bind it to the immutable released artifact. |
| PostgreSQL transport encryption / server identity | P0 security / #123 | Complete realistic TLS-enabled PostgreSQL acceptance, identity verification, downgrade refusal, recovery, and caller-owned policy. |
| Component-image dependency surface | Repaired on #323 | Preserve no-`libpq5`, no-runtime-pip, admitted-driver construction, health, and container/PostgreSQL acceptance through protected release. |
| Public commercial surface | Child #321 / live evidence | Keep only `README.md` + `docs/index.md`, non-force reconcile after parent movement, and reacquire exact-child acceptance. |
| Dependency-root governance | External owner paths / non-passing | #233 still requires then-live central CodeQL/OpenCode/Noema settlement and qualifying independent approval. |
| Immutable product release | Not published | After protected integration, publish and verify version/CHANGELOG/tag/package/license/vulnerability/SBOM/provenance/reproducibility/rollback evidence. |
| Context Graph / EA projection | Candidate-only until released authority exists | Adopt only released contracts from canonical owners; never pin mutable producer branches. |

## Commercial acceptance for issue #322

Completion requires all of the following on the final production graph and immutable release:

- parameterized SQL and injection-safe bindings remain intact;
- commit, rollback, context-manager, cleanup-error precedence, cancellation/recovery, and connection lifecycle remain deterministic;
- tenant authority and transaction-local `set_config` behavior remain correct under forced RLS and restricted roles;
- JSON/JSONB, UUID, timestamp, row, row-count, and relevant PostgreSQL error semantics remain compatible;
- DSN parsing/rendering preserves supported URI, keyword, and explicit-service-selector contracts without credential leakage into argv or logs;
- explicit service-file capability cannot be redirected by final symlink/path substitution, later CWD changes, replacement of the selected parent directory, or replacement of the construction-selected regular-file inode;
- concurrency, idempotency, checkpoint, schema application, logical restore, health, and finite-connect behavior pass realistic PostgreSQL tests through the production selector;
- the committed default runtime graph and built artifacts contain no disallowed GPL/LGPL/AGPL-family package;
- the component image retains neither superseded `libpq5` nor inherited Python packaging executables and can construct the admitted pg8000 selector from its final no-dev environment;
- retained Psycopg verification dependencies stay outside production/default installation and release runtime evidence;
- package, license, vulnerability, validated SBOM, provenance, and reproducibility evidence bind the same immutable artifacts;
- the final unchanged protected head passes exact-source required checks and live review/ruleset requirements without self-approval or gate weakening; and
- #322 completion is not represented as #123 transport-security completion.

## Context Fabric boundary

`context-graph-contracts` remains the contract-only Shared Kernel for canonical object/authority references, truth origin/status, bitemporal semantics, provenance, Context Assertion, CloudEvents/schema/conformance/admission contracts. `enterprise-architecture-core` remains the EA Decision Plane. pg-llm-batch consumes only released contracts through explicit anti-corruption boundaries.

Prompt, response, batch-result, and user data remain pg/product-domain data and are not copied into EA authoritative architecture tables. Deployable service/API/worker/database/runtime/provider/version and lifecycle/risk/ownership/remediation changes may be projected only through a verified released Context Graph contract with provenance.

## Evidence discipline

Queued, pending, skipped-required, `action_required`, cancelled, absent, predecessor-head, model-only, and status-only evidence is non-passing. A pg-owned defect requires a realistic RED, smallest causal repair, focused/full GREEN, and exact-head refetch. A foreign-owned prerequisite must advance at its canonical owner. A report, comment, or documentation-only change is not completion while executable code/test/restack/release work remains.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: SSL support*. https://www.postgresql.org/docs/18/libpq-ssl.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: The connection service file*. https://www.postgresql.org/docs/18/libpq-pgservice.html

Python Software Foundation. (2026). *Python 3.14.7 documentation: os — Miscellaneous operating system interfaces*. https://docs.python.org/3.14/library/os.html

Locke, T. (2025). *pg8000 1.31.5: Python interface to PostgreSQL*. PyPI. https://pypi.org/project/pg8000/1.31.5/

Step Security. (2026). *sbom-action source at a2040c89fdf602b1abf5d2f46ac2c83bc6b341b7*. GitHub.

Anchore. (2026). *Syft v1.51.1*. GitHub release.
