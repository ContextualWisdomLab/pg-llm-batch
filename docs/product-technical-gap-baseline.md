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

`load_pg8000_driver()` obtains one installed `Distribution` metadata snapshot, requires that object's version to equal the admitted pg8000 version, and reuses the same object to derive the expected package root. The top-level package spec must resolve exactly to that admitted root before import. After Python resolves `pg8000.dbapi`, the loader also requires the returned module's `__file__` to resolve to that same root's `dbapi.py` before the module receives adapter or connection authority. Filesystem/path-resolution failures during these origin checks are normalized to the same fixed content-free origin-admission error rather than exposing environment-specific lookup details. This prevents separate version/origin metadata snapshots and stale or preloaded module-cache entries from silently transferring connection authority to different package bytes while keeping unadmitted path states inside one fail-closed boundary. Optional service-file support remains explicitly caller-selected; unsupported multi-host/socket/query/LDAP/ambient-service semantics remain fail closed rather than being approximated.

The branch preserves realistic PostgreSQL acceptance for parameter binding, no-parameter DB-API execution, row normalization and exact/unknown row counts, transaction/context ownership, cleanup precedence, terminal connection state, thread-affine use, tenant/RLS/session behavior, UUID/timestamp and JSONB adaptation, SQLSTATE classification, checkpoint/recovery, schema/restore behavior, package-installed execution, and supported-Python runtime smokes.

The production-like no-dev graph and component image also preserve exact dependency/source digests, positive license admission, CycloneDX SBOM policy, source-wheel parity, removal of superseded `libpq5`, and removal of inherited Python 3.14 pip/setuptools/wheel installation authority while still constructing the admitted pg8000 driver.

### Public commercial surface: PR #321

PR #321 owns only `README.md` and `docs/index.md` relative to #323. Its exact head, merge base, checks, and review state are intentionally not pinned here. Every run must read the child live, require its merge base to equal the then-current #323 head, require only those two relative paths, advance it through ordinary non-force ancestry, and reacquire exact-child acceptance after every parent movement. Parent/predecessor GREEN is ancestry evidence only.

## Runtime-graph RED and causal repair

The selector and manifest were promoted before the committed lock converged. Exact `8972ec9a1f1e94ad40b5490be88e5e53d1dd200b` demonstrated that frozen/default installation could still install Psycopg while the production selector required pg8000. `e1045b6ed74e848cd99a50b02b42fe731fcc8b9b` regenerated the lock and proved the default graph contains pg8000 and excludes Psycopg.

A later production-promotion RED at `3e0103fcf0a94327828b62137666f52fa12b6561` exposed three post-cutover defects: CLI confidentiality had become coupled to the narrower concrete-driver grammar, a workflow contract still asserted the pre-promotion dependency state, and packaged restore smoke imported removed Psycopg. Minimal repair `2afd5be12847b51c8d476c59f5b328c697069780` separated argv-secret classification from concrete-driver connectability, updated the dependency contract, and routed restore acceptance through `retained_postgres_driver()`.

## Installed-driver metadata authority RED and repair

The production loader previously performed version admission with `distribution_version("pg8000")` and then performed import-root admission from a separate `distribution("pg8000")` lookup. Each lookup was individually reasonable, but together they left an unnecessary split-authority window: an admitted version result could be combined with a different installed-distribution metadata object before package import.

Test-first `0e056c160c2cf6b5e769a7aaaa9a12883a10e9af` made the version lookup report admitted `1.31.5` while the distribution object used for origin authority reported unadmitted `1.31.4`, and required package import to remain blocked. Exact CI `34303889337`, Python 3.12 job `102316430972`, produced the real RED: `test_loader_rejects_split_version_and_origin_metadata_before_import` reached the forbidden import path; the job ended `1 failed, 1662 passed, 5 deselected`.

Test-contract descendant `c405859f67e4c21974c18f735971e07d5d009487` expresses admitted and mismatched versions on the same distribution fixture. Minimal production repair `e497dfc8630de86563c9bcb9b9bd33acb99a9685` removes the independent version lookup: one `Distribution` object now supplies both `.version` admission and the expected package root used by import-origin admission.

This closes the split metadata-snapshot authority defect. It does not claim that arbitrary runtime filesystem mutation is impossible, and it does not replace the immutable package/SBOM/provenance/reproducibility evidence required for release.

## Imported DB-API module authority RED and repair

Python's import system checks the module cache before asking finders to resolve a module. The loader therefore had a second authority gap after the one-snapshot metadata repair: the admitted top-level `pg8000` package spec could point at the expected installed distribution while `import_module("pg8000.dbapi")` returned a stale or preloaded module object from another filesystem location.

Test-first descendants `e0eaa3c6296936f1f7e49bcd266a1d19346f9907` and `3cb4eba577fb069a6d7d2b5b28eb520fd623eabb` require both a DB-API module outside the admitted root and a returned module without usable `__file__` metadata to fail closed. Their hosted workflows were cancelled by ordinary descendant publication before completing and are not counted as hosted RED evidence. A focused executable reproduction against the then-current loader semantics admitted both the shadow module and the missing-origin module, establishing the causal behavior without treating cancelled workflow state as GREEN or RED.

Minimal production repair `b5620ec54ca2ffa84b118cf546610aae63775381` reuses the expected package root derived from the already admitted `Distribution`, checks the top-level package spec before import, and then validates that the actual returned `pg8000.dbapi.__file__` resolves exactly to `<admitted-root>/dbapi.py` before handing the module to `Pg8000DriverAdapter`. Missing or mismatched returned-module origin fails closed with the existing content-free driver-origin diagnostic. This does not claim defense against arbitrary hostile mutation inside the trusted Python process; it binds normal installed-artifact and module-cache authority at the production loader boundary.

## Origin-resolution diagnostic boundary RED and repair

The admitted-root and returned-module comparisons still called `Path.resolve()` directly. A filesystem lookup failure, invalid concrete path, or historical symlink-loop resolution failure could therefore escape the production loader as a raw path exception before the fixed driver-origin diagnostic was applied. That leaked environment-specific failure behavior at the same boundary intended to make unadmitted package/module authority content-free and fail closed.

Test-first `0f7339e43e9597c55e396cab4154e0aa2c0e825f` adds installed-root and returned-DB-API origin-resolution regressions. Its exact CI `34309660779` was later cancelled by ordinary descendant publication, but Coverage/docstrings/lint/package job `102333507818` completed first with failure at `Enforce line coverage`; that completed exact-head job remains hosted RED evidence. Release Acceptance `34309660785` succeeded on the same test-only head and does not override the failing CI job.

Minimal repair lineage `79d9d693a1e11bdeacbb2feb471baaba7f0455a5` → `de98ccf1a7a0bb71f447e4ed8bcb273b66871b68` introduces one `_resolve_origin_path()` boundary and normalizes `OSError`, legacy symlink-loop `RuntimeError`, invalid-path `ValueError`, and invalid path-like `TypeError` to `Pg8000DriverUnavailableError("PostgreSQL driver origin is not admitted")`. Successful origin comparison semantics and the one-distribution/returned-module authority model are unchanged. Exact source-head CI `34309877228` and Release Acceptance `34309877270` both completed successfully before this documentation descendant was created; the documentation descendant must reacquire its own exact-head acceptance.

Python's concrete `pathlib` filesystem methods document `OSError` as a normal filesystem failure surface, while `Path.resolve()` also has version-specific symlink-loop behavior. The product contract therefore treats path resolution as fallible I/O and owns its diagnostic normalization instead of exposing implementation-specific filesystem details.

## Explicit service-file authority RED and repair

The explicit `pg_service.conf` capability is caller-selected and bounded. It does not perform ambient `PGSERVICEFILE`, user/system service-file, LDAP, or filesystem search discovery. Five independent authority defects have been repaired.

First, final-component symlink/path substitution during a read could redirect the selected file. `63ef822c2b48cf4ff2d9dddcf8641ba0ca652ff3` added regular non-symlink selection, descriptor authentication, bounded reads, before/after metadata stability, strict UTF-8/NUL rejection, and generic non-content-bearing diagnostics.

Second, retaining a relative path allowed a later `chdir()` to change the selector. Test-first `3efb40078efeb64ea28bebaf28b2795265c04d1f` produced a real CI RED; `2077809188cbc0f0dd8bb7f2f11af859b4ad15ed` binds relative selection to its construction-time absolute path.

Third, absolute binding still left the selected parent pathname replaceable. Test-first `a7bb3ea76ad9747b83f517d518b2ddf22fdd7e92` reproduced parent replacement; `3dc5dad088ff8732d9e3b9a715f2f6e7e467e862` retains the construction-time parent identity and authenticates the reopened directory descriptor before final-component operations.

Fourth, parent identity plus per-read final identity did not retain the selected regular-file identity across resolver construction and later resolution. Test-first `491e9dc9349a816e37e015c8752e81b973c1ab95` reproduced same-parent atomic replacement. Repair `71922a5ed1231049e235e165490f514fd53c9f6a` captures the selected final regular-file `(st_dev, st_ino)` at construction and requires the same identity before and after later opens.

Fifth, retaining the selected inode still allowed same-inode truncate/rewrite after resolver construction. Test-first `2217ab106f26162f6f10d9ecb6937817463bdc80` proved the inode remained unchanged while connection parameters changed and produced a real CI RED. Repair `023a8d138584c38bdaa717a68b7f2f79286a9497` retains a SHA-256 digest of the bounded, strictly decoded construction-time bytes and requires that digest to match after later descriptor-authenticated reads before service parsing. Plaintext content is not retained as the marker and diagnostics remain content-free.

These filesystem/content-capability controls prove selector authority, not remote TLS/CA/hostname policy. Issue #123 remains separate.

## Production SBOM RED and causal repair

Issue #322 requires the final default graph, package, and SBOM to exclude disallowed GPL/LGPL/AGPL-family dependencies. The branch generates CycloneDX evidence from the production-like no-dev environment after installing the exact package and hash-verified pg8000 closure, fails closed if pg-llm-batch or pg8000 is absent, if Psycopg appears, or if GPL/LGPL/AGPL-family license evidence appears, and preserves the validated SBOM as evidence.

The first production workflow configuration used a bare Syft version and produced a real HTTP-404 CI RED before Syft executed. Inspection of the pinned action showed its installer expected the v-prefixed release tag; `bc774185a4ba3fcbebe924aa1051154c3a713339` corrected the production value to `v1.51.1`. This remains Draft evidence until bound to an immutable protected release.

## Component-runtime minimization

After pg8000 became the production graph, the component image still installed `libpq5`. Test-first acceptance made that stale native dependency a RED; the repair removed it, retained the health-check dependency, and added final-image proof that `libpq5` is absent while the copied no-dev environment can construct `retained_postgres_driver()`.

The image had also moved to Python 3.14 while cleanup still targeted Python 3.11 packaging tools. The corrected runtime removes Python 3.14 pip/setuptools/wheel installation authority and fails image construction if `pip`, `pip3`, or `pip3.14` remains discoverable. These changes reduce mutable installation surface but are not a complete container-hardening claim.

## Transport-security boundary

Issue #322 does not close issue #123. Successful pg8000 connections, installed-distribution and returned-module admission, explicit service-file path/parent/inode/content authority, production SBOM policy, no-`libpq5`, and no-runtime-pip evidence do not prove mandatory verified remote TLS or authenticated server identity.

Issue #123 remains canonical for package-created remote TCP connections, deliberate local/embedding-host exceptions, trusted CA plus matching hostname, wrong-CA and hostname-mismatch rejection, plaintext/downgrade refusal, server SSL refusal, restart/recovery, bounded diagnostics, and caller-owned connection non-interference.

## Highest-priority gaps

| Gap | Current state | Required next evidence |
| --- | --- | --- |
| Commercial PostgreSQL runtime dependency | P0 / active Draft | Preserve the pg8000 default graph through normal prerequisite integration, obtain one unchanged final #323 head, merge normally, then bind immutable protected-release evidence. |
| Installed-driver + imported-module authority | Repaired on #323 / exact hosted revalidation required | Preserve one-snapshot version/package-root admission, returned DB-API module-origin binding, and normalized origin-resolution diagnostics through final package, exact-head CI, and protected release. |
| Explicit service-file authority | Repaired on #323 | Preserve construction-time absolute path, parent identity, selected regular-file identity, selected-content digest, descriptor-relative I/O, bounded parsing, and generic diagnostics through final integration/release. |
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
- installed pg8000 version and expected package root are admitted from the same installed-distribution metadata snapshot before import, the actual returned `pg8000.dbapi` module origin matches that same admitted root before connection authority is granted, and origin-path resolution failures are normalized to the fixed non-content-bearing admission diagnostic;
- explicit service-file capability cannot be redirected by final symlink/path substitution, later CWD changes, replacement of the selected parent directory, replacement of the construction-selected regular-file inode, or in-place mutation of the construction-selected file content;
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

Python Software Foundation. (2026). *Python 3.14.7 documentation: The import system — The module cache*. https://docs.python.org/3.14/reference/import.html#the-module-cache

Python Software Foundation. (2026). *Python 3.14.7 documentation: importlib.metadata — Accessing package metadata*. https://docs.python.org/3.14/library/importlib.metadata.html

Python Software Foundation. (2026). *Python 3.14.7 documentation: pathlib — Object-oriented filesystem paths*. https://docs.python.org/3.14/library/pathlib.html

Python Software Foundation. (2026). *Python 3.14.7 documentation: hashlib — Secure hashes and message digests*. https://docs.python.org/3.14/library/hashlib.html

Python Software Foundation. (2026). *Python 3.14.7 documentation: os — Miscellaneous operating system interfaces*. https://docs.python.org/3.14/library/os.html

Locke, T. (2025). *pg8000 1.31.5: Python interface to PostgreSQL*. PyPI. https://pypi.org/project/pg8000/1.31.5/

Step Security. (2026). *sbom-action source at a2040c89fdf602b1abf5d2f46ac2c83bc6b341b7*. GitHub.

Anchore. (2026). *Syft v1.51.1*. GitHub release.