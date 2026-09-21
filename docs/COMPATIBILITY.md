# Compatibility and deprecation policy

This policy defines the package-owned compatibility boundary for `pg-llm-batch` as a standalone and embeddable PostgreSQL batch component. It is intentionally narrower than “everything that currently works”: compatibility promises attach only to reviewed public contracts and immutable release evidence, not to incidental implementation details or a mutable branch head.

The repository follows Semantic Versioning. Because the current package version is pre-1.0, this policy deliberately provides a stricter project rule than SemVer's default allowance for arbitrary `0.y.z` changes: ordinary breaking changes are not allowed in a patch release, and planned removals require an explicit deprecation path. A fail-closed security correction may override that ordinary compatibility path when preserving prior behavior would preserve unsafe behavior.

## Compatibility surface

The compatibility surface is the reviewed set of contracts that a caller, operator, embedding host, or durable consumer is expected to depend on:

- names intentionally exported through `pg_llm_batch.__all__`, including their documented call signatures, return shapes, package-owned value objects, and bounded exception contracts;
- documented public entry points outside the top-level export list when the project explicitly designates them as supported;
- the `pg-llm-batch` command-line interface, including documented commands/options, exit-code semantics, and documented machine-readable output fields;
- documented serialized evidence formats whose bytes, fields, or digest identity are exposed for persistence, verification, audit, or interchange;
- the durable PostgreSQL schema, migration ordering, tenant/RLS invariants, conflict identities, and supported upgrade/rollback behavior required to read or operate package-owned persistent state; and
- embedding seams that explicitly leave caller-owned connections, providers, credential resolvers, exporters, or host authorization as host authority while keeping package-owned validation and persistence contracts under package version authority.

A symbol appearing somewhere under `pg_llm_batch` is not public merely because Python can import it. Private/internal modules, underscored helpers, tests and fixtures, generated artifacts, local workflow implementation details, undocumented database internals, transitory branch-only experiments, and mutable provider-specific details are outside the compatibility surface unless another reviewed public contract explicitly adopts them.

The current membership of `pg_llm_batch.__all__` is therefore evidence of the current top-level public surface, not a promise that every current implementation detail is permanent. Changes are classified against the reviewed contract represented by those public names and their documented behavior.

## Pre-1.0 versioning

Until `1.0.0`, the project uses `0.MINOR.PATCH` with the following compatibility rule:

- a PATCH release is limited to backward-compatible fixes, hardening, evidence corrections, and documentation changes, except for the security-correction rule below;
- a MINOR release may add backward-compatible public functionality and may complete a previously announced removal whose earliest removal version is that MINOR or earlier;
- a planned backward-incompatible change must be identified as such in review, migration guidance, and the CHANGELOG. Outside an urgent security correction, it must not first appear as an unannounced PATCH change;
- a new deprecation records an explicit earliest removal version. The earliest removal version must be later than the version that first ships the deprecation; and
- reaching `1.0.0` means the declared public compatibility surface is governed by ordinary Semantic Versioning MAJOR/MINOR/PATCH rules.

Pre-1.0 does not turn undocumented behavior into a contract, nor does it permit a released artifact to be mutated in place.

## Deprecation lifecycle

A deliberate deprecation has five pieces of evidence before removal:

1. **Introduction.** The deprecated public contract and its replacement or migration alternative are identified in reviewed source/documentation and the CHANGELOG.
2. **Warning.** Where runtime or command-line warning is appropriate, the warning uses a package-owned bounded diagnostic. Deprecation evidence must not reflect arbitrary caller/provider content.
3. **Migration.** The supported replacement path is documented, including data/schema migration when durable state is affected.
4. **Earliest removal version.** The deprecation records an explicit earliest removal version that is later than the version introducing the deprecation. A date alone is not sufficient version authority.
5. **Removal.** Removal occurs only in an eligible version under the pre-1.0 rule above or, after `1.0.0`, an eligible MAJOR release. Release notes identify the removal and the completed migration path.

Warnings and deprecation diagnostics must remain content-minimal. They must not expose credentials, secrets, prompts/results, tenant identifiers, provider identifiers, remote batch identifiers, DSNs, arbitrary exception text, request/response bodies, or other unbounded caller/provider content merely to explain a deprecation.

A deprecation test should assert the contract at the appropriate abstraction level. It should not freeze irrelevant implementation structure or make a reviewed compatibility change impossible to express.

## Security corrections

Compatibility does not require retaining unsafe behavior. A reviewed vulnerability fix or trust-boundary correction may intentionally break behavior when retaining the old behavior would keep a security or privacy defect exploitable. Such corrections are **fail closed**: invalid or untrusted authority is rejected rather than accepted for compatibility's sake.

When a security correction changes a public behavior, the change must:

- identify the affected compatibility contract without publishing exploit material that should remain confidential;
- preserve fixed, bounded diagnostics and avoid reflecting credentials, tenant identities, provider content, DSNs, secrets, or arbitrary attacker-controlled values;
- describe the safe migration or mitigation where one exists;
- record the change in release notes/CHANGELOG with the exact fixed source and package/release identity once released; and
- retain required tenant authorization, PostgreSQL RLS, credential, transport, filesystem, and other security invariants rather than weakening a gate to preserve unsafe behavior.

An emergency security correction may skip the ordinary deprecation waiting period. That exception does not authorize silent gate weakening, mutable-release replacement, unsupported downgrade, or omission of migration/rollback evidence where durable state changes.

## Durable data and rollback

Compatibility for durable PostgreSQL state is defined by executable migration and recovery behavior, not by schema text alone.

A change to the PostgreSQL schema, durable evidence format, tenant key, conflict identity, constraint, index relied on for correctness, or RLS policy must document and test the supported migration path before it can be claimed compatible. The package must preserve the repository's tenant/RLS invariants: validated tenant context precedes package database access; lifecycle identity is tenant-qualified where required; application roles do not rely on superuser/BYPASSRLS privileges; and migrations that temporarily relax owner enforcement restore forced RLS atomically as required by the owning migration contract.

For every durable breaking risk, the change must state which combinations are supported:

- new writer -> old reader;
- old writer -> new reader;
- upgrade from the previous supported schema/release; and
- rollback or recovery after the migration.

If a downgrade, old-reader combination, or rollback cannot be made safe, the package must reject it deterministically and fail closed rather than silently reinterpret durable data. A destructive or irreversible migration requires explicit recovery evidence and cannot be described as rollback-compatible merely because source code can be reverted.

Packaged and container initialization schema copies that are contractually required to match must remain synchronized. Cross-service SQL and source-copying another owner service's domain truth are not compatibility mechanisms.

## Release evidence

A compatibility claim is bound to an exact source, package, and release identity. A branch SHA, pull request, version literal, `[Unreleased]` CHANGELOG section, successful CI run, or locally built artifact is not by itself a released compatibility authority.

For a release to carry this policy's compatibility claim, the accepted protected source must be tied to the package version and immutable publication evidence required by the release-governance owner. Applicable evidence includes the exact source commit, version/CHANGELOG decision, built package artifacts, checksums, SBOM, provenance/attestation, reproducibility result, release record/tag where used by the canonical release process, and rollback/recovery material. Published release contents are not mutated in place; a correction is a new version/release.

Compatibility tests must run against the same exact candidate source whose package/release evidence is accepted. Evidence from a predecessor head does not transfer after source or base movement. Security/SAST, supported-Python, PostgreSQL/container, package/build/install, owned production coverage/docstrings, review/thread resolution, and other then-live protected governance gates remain part of release acceptance when applicable.

Changes to the command-line interface, serialized evidence, `pg_llm_batch.__all__`, PostgreSQL schema/migration behavior, or other public contract must be classified and recorded before release. The classification must explain whether the change is backward compatible, a deprecation, an intentional breaking change, or a fail-closed security correction, and must point to the migration/rollback evidence required by that classification.

## References

Semantic Versioning. (n.d.). *Semantic Versioning 2.0.0*. https://semver.org/spec/v2.0.0.html
