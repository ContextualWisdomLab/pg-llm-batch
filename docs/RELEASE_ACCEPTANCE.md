# Release Acceptance, Rollback, and Provenance Contract

- **Document maturity:** ACTIVE-PR on the canonical documentation branch until protected integration
- **Current protected package baseline:** version `0.1.0`

## 1. Release authority

A pg-llm-batch release may be created only from one **exact integrated protected head** after every applicable deterministic, security, compatibility, migration, operational, review, packaging, SBOM, provenance, and publication gate has been evaluated for that exact revision.

A feature PR, stacked branch, synthetic merge commit, predecessor-head check, status-only review, draft release artifact, or locally built package is not release authority.

## 2. Required evidence classes

Release acceptance keeps the following authorities separate:

- exact integrated protected source revision;
- independently resolved protected branch identity;
- repository CI and test evidence for the commit actually checked out;
- security/SAST/dependency and supply-chain evidence;
- package/wheel/sdist identity and installability evidence;
- migration/rollback/recovery evidence where persistence changed;
- runtime **operational acceptance** for changed health/deployment/operator paths;
- formal semantic review and qualifying **independent** non-author approval where required;
- SBOM and provenance/attestation evidence where the release policy requires them; and
- final published artifact identity after publication.

One evidence class cannot silently substitute for another.

## 3. Quality gate

The exact release candidate must pass the live repository's complete quality contract. At minimum, where currently configured, that includes:

- supported Python-version tests;
- realistic unit/integration/security/concurrency/compatibility tests;
- exact **100%** owned production statement and branch coverage, plus line/function metrics where exposed;
- 100% public docstring coverage;
- compilation and lint;
- lockfile freshness;
- package build and clean installation checks;
- Docker Compose validation and image build where those artifacts are part of the release; and
- canonical documentation fitness.

A coverage percentage does not replace domain-validity tests. A passing unit suite does not replace live PostgreSQL evidence for migration, RLS, transaction, concurrency, or rollback behavior when those contracts changed.

## 4. Security gate

Release acceptance requires zero known valid unresolved security findings within the release scope and successful applicable repository security workflows. Security evidence should include, where configured, SAST, dependency/vulnerability scanning, secret scanning, supply-chain checks, and least-privilege workflow review.

Provider bodies, credentials, DSNs, tenant identities, secret values, and other protected data must remain outside release logs/artifacts except where an explicitly authorized evidence contract requires a bounded representation.

## 5. Migration and rollback gate

When a release changes PostgreSQL persistence, the release candidate must prove:

1. forward migration from every supported source state;
2. idempotent or explicitly one-shot semantics as designed;
3. concurrency/locking behavior under realistic PostgreSQL execution;
4. failure atomicity or documented partial-commit recovery;
5. retained-data preservation;
6. rollback behavior, including fail-closed refusal when rollback would destroy retained evidence; and
7. operator recovery steps for a failed or interrupted deployment.

A Docker initialization script is not an upgrade mechanism for existing volumes unless a reviewed contract explicitly says otherwise.

## 6. Compatibility gate

The release candidate must agree with `docs/product/API_CONTRACT.md`, package metadata, README, PRD/TRD, architecture, schema/ERD, and CHANGELOG.

Breaking Python API, CLI, schema, deployment, or evidence-format changes require the versioning/deprecation treatment documented in the API contract. ACTIVE-PR behavior must not be advertised as shipped.

## 7. Reproducibility and artifact identity

Protected main currently has normal package build capability. Descriptor-pinned clean-archive reproducibility and stronger artifact-identity evidence are **ACTIVE-PR** work until their implementation integrates.

When reproducibility/provenance is required for a release, acceptance must bind evidence to the exact release source rather than trusting path names or prior build output. The intended target is to:

- build wheel and source distribution from a clean exact-source archive under deterministic inputs;
- build independently more than once and compare bytes where the supported toolchain promises reproducibility;
- verify artifact distribution name/version and package metadata;
- hash artifacts from a race-resistant file identity boundary;
- produce bounded canonical release evidence;
- generate an SBOM from the accepted source/dependency closure;
- generate or attach provenance/attestation through separately governed publication authority; and
- verify the published artifact after release.

An unkeyed SHA-256 hash is identity/change-detection evidence, not by itself signing, provenance, authentication, or publication authority.

## 8. Independent review and merge governance

Release preparation does not permit self-approval, synthetic approval, weakened protection, or reuse of reviews anchored to an older source head. Where live repository/CWL governance requires a qualifying independent non-author review, that approval must apply to the unchanged accepted source head.

A COMMENTED review, commit status, bot text, reaction, dismissed review, author review, or model verdict is not automatically equivalent to formal independent approval.

## 9. Operational acceptance

After source integration and before publication, changed operator/runtime surfaces must be exercised from protected main where practical. Depending on the release, operational acceptance includes:

- schema initialization or supported upgrade path;
- component startup and readiness;
- bounded `/healthz` behavior;
- credential/config bootstrap without secret disclosure;
- submit/poll/wait/retrieve lifecycle against an approved compatible provider or deterministic contract harness;
- migration/recovery paths;
- container/Compose startup and intended network exposure;
- observability that does not alter application behavior; and
- explicit degraded/failure behavior.

Operational acceptance records the exact source/artifact and environment assumptions used. A green source PR alone is not runtime closure.

## 10. CHANGELOG and version decision

Before publication:

1. verify the exact integrated protected head;
2. select the next Semantic Version according to the compatibility impact;
3. move accepted user/operator-visible entries out of `Unreleased` as appropriate;
4. update package version metadata once, consistently;
5. keep the CHANGELOG aligned with protected-main reality; and
6. do not include unmerged target capabilities in released notes.

## 11. Publication

Publication credentials and OIDC/registry authority must be separate from ordinary pull-request verification where practical. Pull-request jobs should remain read-only with respect to package registries and release creation.

The publication step must use the exact accepted artifacts, not silently rebuild from a different source revision. After publication, independently resolve the registry/release artifact and verify expected name, version, hashes, metadata, and provenance links.

## 12. Rollback and recovery

A release rollback is a controlled product operation, not `git reset` plus hope. Choose the recovery path based on what crossed an external boundary:

- **Code-only defect before data migration:** redeploy the last accepted artifact if compatibility permits.
- **Forward-compatible additive migration:** application rollback may be possible while retaining the added schema; document the supported version matrix.
- **Irreversible or data-transforming migration:** prefer a forward corrective migration or restore from verified backup according to the migration ADR/runbook.
- **Published bad artifact:** stop promotion, mark/yank only when registry policy and consumer safety permit, publish a corrected version rather than rewriting an immutable release, and preserve incident evidence.
- **Credential/security exposure:** rotate/revoke affected credentials, preserve bounded incident evidence, and do not rely on package rollback alone.

Rollback must never delete retained checkpoint/audit evidence merely to satisfy an older schema expectation.

## 13. Release rejection conditions

Reject release when any of the following is true:

- source head or protected-base identity changed after evidence collection;
- a required check is queued, pending, skipped, cancelled, absent, stale, neutral-required, rate-limited, or failed;
- a valid unresolved source/security finding remains;
- required independent approval is absent;
- migration/rollback or operational evidence is missing for a changed contract;
- package, SBOM, provenance, or reproducibility evidence refers to a different source/artifact;
- documentation advertises ACTIVE-PR behavior as shipped; or
- publication would rely on invented, over-broad, or unverified credentials/permissions.

## 14. Post-release verification

After publication, verify the released artifact as a consumer would:

- resolve the release/version from the official registry/release channel;
- validate package metadata and license/NOTICE inclusion;
- compare expected hashes/provenance;
- install in a clean supported environment;
- execute a bounded smoke/health path; and
- record any incident or rollback decision without mutating historical release evidence.

Only then is publication evidence complete.

## 15. References

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

OpenSSF. (n.d.). *Supply-chain Levels for Software Artifacts (SLSA)*. https://slsa.dev/

Preston-Werner, T. (n.d.). *Semantic Versioning 2.0.0*. https://semver.org/spec/v2.0.0.html
