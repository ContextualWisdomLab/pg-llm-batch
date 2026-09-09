# Product and technical gap baseline

This baseline separates protected/shipped truth from active-PR evidence. Exact refs, PR heads/bases, reviews, required checks, rulesets, security results, releases, and descendant topology must be read live before merge or release decisions; this file is not a substitute for GitHub evidence.

## Product boundary

pg-llm-batch owns durable PostgreSQL-backed asynchronous LLM batch preparation and execution records, token/size accounting, provider-neutral `BatchInferencePort` lifecycle state, tenant/RLS enforcement, result ingestion, audit/provenance, recovery, and the PostgreSQL driver boundary required to support those capabilities. Provider/model discovery and routing remain contextual-orchestrator authority. Foreign domain truth is consumed only through released versioned contracts and anti-corruption layers; source copying, mutable-branch production dependencies, and cross-service application-table SQL are out of bounds.

The commercial driver migration does not transfer PostgreSQL transport-security authority into issue #322. Package-wide remote TLS, trusted-CA/hostname verification, downgrade/plaintext refusal, and caller-owned connection-policy acceptance remain issue #123 authority.

## Protected-main truth

The protected integration branch remains `main`; at this refresh its exact head is `5913c4bad79d6bc29d7cc1c624abb7db2ea6a77c`. The package remains version `0.1.0`, and protected main still carries the Psycopg production runtime graph. Therefore issue #322 is still an open shipped/release defect even though the active migration branch has a pg8000 production graph and stronger supply-chain evidence.

There is still no immutable GitHub Release. A GREEN Draft branch is not release authority. The pg8000 graph must first integrate through the protected workflow; one exact protected head must then bind version/CHANGELOG/tag/package/license/vulnerability/SBOM/provenance/reproducibility/rollback evidence before #322 can close.

## Active delivery lanes

### Dependency root: PR #233

PR #233 remains the dependency-root integration prerequisite at exact `01d231fde23b82e2ced258d7bfcb4721ed75706d`. Its repository-local deterministic lanes are successful, while required compatibility CodeQL, OpenCode, Noema, and a qualifying independent approval remain non-passing owner prerequisites. Canonical central CodeQL repair remains `.github#2040@6706c231ab06a3c91c43fdb5b989cfcd79fff593`; its Security Scan, Semgrep, Python Security, and Agent Review Runtime Quality are successful while CodeQL `34251822255` remains terminal failure. Leaf churn, synthetic status, self-approval, gate weakening, or routine administrator bypass are not substitutes. pg-llm-batch must consume protected central workflow behavior rather than copy mutable central source.

### Commercial PostgreSQL driver: PR #323

PR #323 is the active Draft migration lane for issue #322. It established `PostgresDriverPort`, retained Psycopg as an optional test/development baseline, proved pg8000 1.31.5 behind the neutral port, and promoted the admitted pg8000 adapter into the branch's centralized production selector. The manifest pins `pg8000==1.31.5` in the default runtime graph; Psycopg 3.3.4 remains only in optional test/development groups for legacy-baseline verification. The default no-dev runtime resolves pg8000 with `python-dateutil`, `scramp`, `asn1crypto`, and `six`, without a Psycopg production edge.

`load_pg8000_driver()` admits only exact pg8000 1.31.5, checks installed-distribution identity and import origin before package code executes, and optionally composes one caller-selected service file. `retained_postgres_driver()` centralizes construction of the admitted adapter. Unsupported multi-host/socket/query/LDAP/ambient-service semantics remain fail closed rather than being approximated.

The branch preserves real PostgreSQL acceptance for parameter binding, no-parameter DB-API execution, tuple-row normalization, finite fetch budgets, exact/unknown row counts, transaction/context ownership, terminal connection state, thread-affine use, tenant/RLS/session behavior, UUID/timestamp round-trip, SQLSTATE classification, cleanup precedence, JSONB adaptation, packaged restore-catalog behavior, server-terminated-session recovery, exact dependency/source digests, license evidence, source-wheel parity, package-installed execution, and Python 3.10/3.12/3.14 PostgreSQL runtime smokes.

The component image follows the same production decision. Exact source repair `b83c6ca7dce1f553c549a1be94bb880274a089ee` removes the stale Python 3.11 cleanup inherited after the image moved to Python 3.14, deletes the Python 3.14 pip/setuptools/wheel packaging toolchain from the final image, fails image construction if `pip`, `pip3`, `pip3.14`, or Debian `libpq5` remain available, and still proves `retained_postgres_driver()` can be constructed from the copied no-dev environment. Exact CI `34291089042` and Release Acceptance `34291089064` are terminal success on that source head. This baseline update is a documentation descendant and must reacquire its own exact-head acceptance before #323 is treated as current-head GREEN.

### Public commercial surface: PR #321

PR #321 owns only `README.md` and `docs/index.md` relative to #323. Exact child `8934de41cb606fb1b3411f9de4ece401447c95a8` is an ordinary two-parent descendant whose first parent is predecessor child `2e5a1b6d580b15c11e07ada10be34e6ebf203e0f` and second parent is then-current #323 `4d5505909f876baf5290e0696472c9c32090e353`. Fresh comparison at that boundary had merge base exactly `4d550590...`, ahead 53 / behind 0, with only `README.md` and `docs/index.md` as relative semantic delta. The child independently reached CI `34292043223` plus Release Acceptance `34292043214`, both terminal success. This baseline commit advances #323 after that child proof, so #321 must be ordinary non-force reconciled again onto the new parent and reacquire exact-child acceptance; predecessor GREEN is ancestry evidence only.

## Runtime-graph RED and causal repair

The selector and `pyproject.toml` were promoted before the committed `uv.lock` converged. Exact head `8972ec9a1f1e94ad40b5490be88e5e53d1dd200b` therefore produced a useful reality RED: frozen/default container installation followed the stale lock and installed Psycopg while the production selector required pg8000. The PostgreSQL/container smoke failed through `retained_postgres_driver()`, and the locked-dependency lane failed before product tests. The correct repair was not a fallback or relaxed frozen installation.

Commit `e1045b6ed74e848cd99a50b02b42fe731fcc8b9b` regenerated and verified the lock, proved the default runtime edge contains pg8000 and excludes Psycopg, ran `uv sync --locked --no-dev`, constructed the admitted adapter, built the package, and removed the temporary finalizer workflow. Its workflow-token-authored PR runs were `action_required` without jobs and are not GREEN evidence.

A later production-promotion RED at `3e0103fcf0a94327828b62137666f52fa12b6561` exposed three post-cutover defects: CLI confidentiality had become coupled to pg8000's narrower connection grammar, a workflow contract still asserted the pre-promotion dependency state, and the packaged restore smoke directly imported removed Psycopg. Minimal repair `2afd5be12847b51c8d476c59f5b328c697069780` separated argv-secret classification from concrete-driver connectability, updated the production dependency contract, and routed restore acceptance through `retained_postgres_driver()`.

## Explicit service-file authority RED and repair

The explicit service-file resolver was hardened through three independent authority defects without enabling ambient `PGSERVICEFILE` discovery.

First, caller-selected final symlinks or path substitution could redirect the selected service file. Production repair `63ef822c2b48cf4ff2d9dddcf8641ba0ca652ff3` retains final-component `(st_dev, st_ino)`, requires a regular non-symlink selection, authenticates the opened descriptor with `fstat()`, preserves bounded reads, before/after metadata stability, strict UTF-8/NUL rejection, and generic non-content-bearing diagnostics. Exact `63ef822...` then exposed a separate 100% coverage RED in CI `34267147130`; focused regression `251cdec97c95f2e842b0fcbeacdd43cd86395c0d` closed the new error-normalization branch.

Second, retaining a relative `Path` allowed later `chdir()` to redirect the same selector. Exact test-first head `3efb40078efeb64ea28bebaf28b2795265c04d1f` produced a real unit-test RED in CI `34272808960`. Minimal repair `2077809188cbc0f0dd8bb7f2f11af859b4ad15ed` binds relative selections to a construction-time absolute path.

Third, construction-time absolute binding still left the selected parent pathname mutable. Exact test-first head `a7bb3ea76ad9747b83f517d518b2ddf22fdd7e92` reproduced parent replacement and failed in CI `34278226597`. Minimal repair `3dc5dad088ff8732d9e3b9a715f2f6e7e467e862` retains the selected parent directory's construction-time `(st_dev, st_ino)`, authenticates the reopened parent descriptor, and performs final-component operations relative to that descriptor. Fixture and coverage descendants culminated in exact `b9dcafb8667b71250b10435fc693fbd678f7322f`, whose CI `34279367790` and Release Acceptance `34279367778` were terminal success with `1657 passed, 5 deselected`, public docstrings 100%, and owned production coverage 100% across 4,677 statements and 1,326 branches.

These filesystem-authority controls do not establish remote TLS/CA/hostname policy; issue #123 remains the separate owner.

## Production SBOM RED and causal repair

Issue #322 requires the final default runtime graph, package, and SBOM to exclude disallowed GPL/LGPL/AGPL-family dependencies. Before this run, #323 already had exact pg8000 wheel/source digests, source-wheel payload parity, positive dependency-license admission, no-dev candidate environments, real PostgreSQL smokes, and reproducible package evidence, but it did not generate and policy-check an SBOM for the exact production-like no-dev runtime environment.

Test-first commit `fe884803eff0ccdece40e8abf68327ee56f8b253` added a release-SBOM workflow contract requiring CycloneDX evidence from `/tmp/pg8000-candidate-py314`, after that environment has received the exact built `pg-llm-batch` wheel and hash-verified pg8000 closure. Its hosted runs were cancelled by an immediate descendant before jobs executed, so the commit is source-level test-first evidence rather than hosted RED.

Production/config descendant `b22783b4475f59e9a1ad9466dbc4e1088bc80e22` then added exact-pinned `step-security/sbom-action@a2040c89fdf602b1abf5d2f46ac2c83bc6b341b7`, CycloneDX JSON output at `release-evidence/production-runtime.cdx.json`, explicit policy validation, and exact-head-named artifact preservation. The validator fails closed if the SBOM lacks `pg-llm-batch` or `pg8000`, includes `psycopg`/`psycopg-binary`, or declares GPL/LGPL/AGPL-family license evidence. The action's dependency-snapshot, automatic artifact, and release-asset publishing are disabled; only the validated SBOM is preserved for evidence.

Exact `b22783b...` produced a real hosted RED in CI `34284615642` while Release Acceptance `34284615604` succeeded separately. The container/runtime job completed image builds, PostgreSQL/legacy smokes, candidate-environment construction, exact pg8000 closure/source digest checks, source-wheel parity, dependency-license admission, exact wheel installation, and `uv pip check`; it then failed at SBOM generation with HTTP 404 before Syft ran. The configured `syft-version` was bare `1.51.1`.

Primary-source inspection of the exact pinned SBOM action proved the cause: its installer URL is constructed as `https://raw.githubusercontent.com/anchore/${name}/${version}/install.sh`, and the action's own default Syft constant is v-prefixed. Passing `1.51.1` therefore targeted a nonexistent git ref; this was an integration/configuration defect, not a product-runtime failure. The test contract was corrected first in `bc6eae25fbbc419f978f0cab90361c51cc7fe36f`, then production workflow repair `bc774185a4ba3fcbebe924aa1051154c3a713339` changed only the corresponding workflow value to `v1.51.1`.

Exact repair head `bc774185...` reached CI `34285340321` and Release Acceptance `34285340333` terminal success. All seven CI jobs succeeded. Critically, the container/PostgreSQL lane completed `Generate production runtime SBOM`, `Verify production runtime SBOM policy`, and `Preserve production runtime SBOM`, then continued through candidate PostgreSQL startup, health acceptance, and real pg8000 smokes on Python 3.10/3.12/3.14. This proves the SBOM workflow on that exact Draft head; it does not prove protected integration or immutable release.

## Component-image libpq RED and causal repair

The pg8000 production graph left a stale native runtime dependency in the component image: its final stage still installed Debian `libpq5` even though the no-dev Python environment had no Psycopg production edge. Test-first exact head `a7b42da27e0bb91f741ec3e26cbf65cc29524536` added a contract rejecting that stale package and produced real CI RED `34289024297`; Release Acceptance `34289024298` succeeded separately and is not substituted for the CI failure.

Minimal source repair `bcfc8c3d4e1511d605077d59da44088f0078948e` removed the direct `libpq5` installation while retaining `curl`, which remains required by the component health check. Evidence descendant `91103597c2f37e36cef3737238d39fe80b2f3307` added a final-image proof that `dpkg-query -W libpq5` must fail and that the copied no-dev environment can construct `retained_postgres_driver()`. Its container/PostgreSQL job successfully built the hardened component image and completed the real PostgreSQL/pg8000 path, but the overall CI `34289301474` was RED because the new proof exposed two stale test-contract assumptions rather than a runtime regression.

Exact `3d277f5146488e3ec351f496c89141cb5316cb0f` made the package-installation assertion precise, and CI `34289483284` then exposed the remaining defects explicitly: `tests/test_component_image_reproducibility.py` still required `libpq5`, while the shared Dockerfile command parser split a semicolon inside the quoted Python proof and raised `ValueError: No closing quotation`. The correct repair was not to restore libpq. Test descendant `a27e22f4ed5ba5a670933b344dd6912f33d79402` retired the obsolete package expectation; final repair `6dbc8461ca0549327077ed16bd2d4763466069eb` expressed the same driver-construction proof without an internal semicolon so the existing command-aware upgrade detector remains valid.

Exact `6dbc846...` reached CI `34289670789` and Release Acceptance `34289670788` terminal success. The component build therefore proves both that the final image contains no `libpq5` package, including transitive installation, and that its no-dev packaged runtime can construct the admitted pg8000 adapter. The same CI also preserves production SBOM policy and real pg8000/PostgreSQL smokes. This removes an unnecessary native runtime surface; it does not claim remote TLS/server-identity completion.

## Component-image Python packaging-toolchain repair

The component image had moved to `python:3.14-slim`, but its cleanup still removed `/usr/local/bin/pip3.11` and Python 3.11 `pip`, `setuptools`, and `wheel` directories. That stale cleanup left the base image's Python 3.14 package-installation authority in the final commercial runtime even though the application executes from the copied no-dev virtual environment.

Test-first commit `98b52e229e9b83cba2970537f0255435c8e87777` added the explicit Python 3.14 cleanup contract. Its CI `34290977814` was cancelled when the branch immediately advanced, so it is source-level test-first evidence rather than a hosted RED; Release Acceptance `34290977972` succeeded separately and is not substituted for the cancelled CI. Minimal repair `b83c6ca7dce1f553c549a1be94bb880274a089ee` corrected the cleanup paths to Python 3.14 and made final-image construction fail if `pip`, `pip3`, or `pip3.14` remains discoverable. It preserves the existing no-`libpq5` and admitted-driver construction proofs.

Exact source repair `b83c6ca...` reached CI `34291089042` and Release Acceptance `34291089064` terminal success. This shrinks the mutable installation surface of the runtime image without claiming that absence of package-manager executables is itself a complete container-hardening or supply-chain guarantee.

## Public-surface RED and repair

An earlier #321 reconciliation exposed a real documentation RED at exact `d546f6d8106cbf41bf5d72fa8e595363c4e7febe` / CI `34260943035`: five current-parent operator/security contracts had been dropped from README while production coverage/docstring gates still passed. Minimal repair `224ed124b675eaf0ec1f558a458286610387500b` restored the 1 MiB `count-tokens` stdin limit, canonical retirement wording for the old SQL provider retriever, the closed transient GET retry-status set, `source_superusers_trusted` logical-restore trust/rollback boundaries, and explicit non-retry rules for TLS handshake/certificate and fingerprint failures. Exact CI `34262344110` and Release Acceptance `34262344236` then succeeded.

#321 remains Draft. Each subsequent parent movement requires ordinary non-force reconciliation and fresh exact-child acceptance; parent success is ancestry evidence, not child acceptance.

## Transport-security boundary remains separate

Issue #322 is a dependency-license/supply-chain migration and does not close PostgreSQL transport-security issue #123. Successful pg8000 connections, explicit service-file authority hardening, production SBOM policy, component-image libpq removal, and packaging-toolchain removal do not prove mandatory verified remote TLS/server identity.

Issue #123 remains canonical for package-created remote TCP connections, deliberate local/embedding-host exceptions, trusted CA/hostname success, wrong-CA and hostname-mismatch rejection, plaintext/downgrade refusal, server SSL refusal, recovery, and caller-owned connection authority. #323/#321 must not present driver migration or SBOM success as TLS completion.

## Highest-priority gaps

| Gap | Current state | Required next evidence |
| --- | --- | --- |
| Commercial PostgreSQL runtime dependency | P0 / active Draft / component image repaired | Reacquire exact-head acceptance after this baseline descendant, preserve the pg8000 default graph through normal prerequisite integration, obtain one unchanged final #323 head, merge normally, then bind immutable protected-release evidence. |
| Production runtime SBOM | Active / exact repair GREEN | Carry validated CycloneDX evidence through protected integration and bind release SBOM to the immutable released artifact. |
| PostgreSQL transport encryption / server identity | P0 security / canonical issue #123 | Complete realistic TLS-enabled PostgreSQL acceptance, verified identity, downgrade refusal, recovery, and caller-owned policy; do not infer from #322. |
| Explicit service-file authority | Active / repaired on #323 | Preserve final-component inode checks, construction-time CWD binding, authenticated parent-directory identity, descriptor-relative I/O, bounded parsing, and fixed diagnostics through final integration/release. |
| Production driver contract parity | Active / promoted on branch | Preserve real PostgreSQL/RLS/recovery/health/migration/package-installed acceptance through the production selector and fail closed on newly proven semantic mismatch. |
| Supply-chain admission | Active / strengthened | Bind exact pg8000 hashes, positive license evidence, vulnerability results, built package, validated SBOM, provenance, reproducibility, and the minimized component runtime to the same immutable release artifact/head. |
| Public commercial-license surface | Child #321 / parent just advanced | Non-force reconcile `8934de41...` onto this new #323 head while preserving only `README.md` + `docs/index.md`, then reacquire exact-child CI/Release. |
| Component-image dependency surface | Repaired on #323 | Preserve no-`libpq5`, no-runtime-pip, admitted-driver construction, health-probe, and container/PostgreSQL acceptance proofs through protected integration and release. |
| Dependency-root governance | External owner paths / non-passing | #233 still requires authenticated current-head central CodeQL/OpenCode/Noema settlement and independent approval before normal protected integration. |
| Immutable product release | Not published | After protected integration, perform and verify version/CHANGELOG/tag/package/license/vulnerability/SBOM/provenance/reproducibility/rollback publication. |
| Context Graph / EA projection | Candidate-only until released authority exists | Do not pin mutable producer heads; adopt only verified released contracts from canonical owners. |

## Commercial acceptance for issue #322

Completion requires all of the following on the final production graph and immutable release, not only candidate fixtures:

- parameterized SQL and injection-safe bindings remain intact;
- commit, rollback, context-manager, cleanup-error precedence, cancellation/recovery, and connection lifecycle remain deterministic;
- tenant authority and transaction-local `set_config` behavior remain correct under forced RLS and restricted roles;
- JSON/JSONB, UUID, timestamp, row, row-count, and relevant PostgreSQL error semantics remain compatible;
- DSN parsing/rendering preserves the supported URI, keyword, and explicit-service-selector contract without credential leakage into argv or logs;
- explicit service-file capability cannot be redirected by final-component symlink, inode substitution, later CWD changes, or replacement of the selected parent directory at the same pathname;
- concurrency, idempotency, checkpoint, schema application, logical restore, health, and finite-connect behavior pass realistic PostgreSQL tests through the production selector;
- the committed default runtime graph and built artifacts contain no disallowed GPL/LGPL/AGPL-family package;
- the component image does not retain the superseded `libpq5` runtime or inherited Python packaging executables, and can construct the admitted pg8000 selector from its final no-dev environment;
- retained Psycopg verification dependencies stay outside production/default installation and release runtime evidence;
- package, license, vulnerability, validated SBOM, provenance, and reproducibility evidence bind the same immutable artifacts;
- the final unchanged protected head passes exact-source required checks and live review/ruleset requirements without self-approval or gate weakening; and
- #322 completion is not represented as transport-security completion; remote TLS/server-identity policy remains #123 authority until separately integrated and released.

## Context Fabric boundary

`context-graph-contracts` remains a contract-only Shared Kernel for canonical object/authority references, truth origin/status, bitemporal semantics, provenance, Context Assertion, CloudEvents/schema/conformance/admission contracts. `enterprise-architecture-core` remains the EA Decision Plane. pg-llm-batch treats them as foreign canonical owners and consumes only released contracts through explicit anti-corruption boundaries.

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