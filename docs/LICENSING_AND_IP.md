# Licensing, IP, and Third-Party Notice Authority

- **Document maturity:** ACTIVE-PR on the canonical documentation branch until protected integration
- **Product license on protected main:** Apache-2.0
- **Package metadata:** `pyproject.toml` declares `license = "Apache-2.0"` and packages `LICENSE` plus `NOTICE`

## Purpose

This document makes the repository's licensing, provenance, ownership, and third-party notice evidence discoverable for release and acquisition due diligence. It records what the repository itself can prove and the checks that must be repeated before a release or transaction. It does **not replace legal review**, title verification, contributor/assignment review, or a transaction-specific freedom-to-operate analysis.

## Outbound license authority

The source distribution declares Apache-2.0 in `pyproject.toml`, carries the complete Apache License 2.0 text in `LICENSE`, and includes `NOTICE` as package license material. Those three artifacts must remain consistent. A release is rejected if package metadata names a different license, either license file is absent from the built distribution, or publication strips required notice material.

The Apache-2.0 declaration is the repository's outbound software-license contract. It does not by itself prove ownership of every historical contribution or satisfaction of every third-party obligation; those are separate provenance and dependency checks below.

## Provenance and ownership evidence

`NOTICE` identifies ContextualWisdomLab as copyright holder for pg-llm-batch and records that the batch core was extracted from the internal `xtrmLLMBatchPython` project and relicensed under Apache-2.0. For acquisition due diligence, that repository statement is evidence to inspect rather than a substitute for underlying corporate IP records.

A transaction or release owner should verify, as applicable:

1. the repository and relevant predecessor history are controlled by the stated owner;
2. material external contributions have a compatible license or documented assignment/contribution right;
3. copied or generated source retains required attribution and license headers;
4. no private/vendor code was introduced without redistribution authority; and
5. the current `NOTICE`, package metadata, and source headers describe the same ownership/licensing boundary.

If any ownership chain is disputed or unavailable, acquisition/release readiness remains unresolved rather than being inferred from a green CI status.

## Third-party dependencies and notices

`NOTICE` currently inventories runtime components and their stated licenses, including PostgreSQL extensions and Python dependencies. That list is a maintained repository declaration, not immutable external truth. Before each release, verify the actual dependency closure against current lock/package/container inputs and authoritative upstream license metadata.

The release process must distinguish:

- direct package dependencies declared by pg-llm-batch;
- optional dependencies such as `cryptography`;
- PostgreSQL extensions installed by the bundled image;
- transitive Python/container dependencies represented in the SBOM; and
- vendored or copied material, if any, which requires source-level notice review rather than dependency metadata alone.

A generated SBOM is inventory/provenance evidence; it does not itself satisfy attribution, NOTICE, source-offer, copyleft, trademark, patent, or other license obligations. Any dependency whose license, origin, or redistribution status cannot be verified fails closed for release/acquisition acceptance until reviewed.

## Release due diligence gate

For an exact integrated release candidate:

1. verify `pyproject.toml`, `LICENSE`, and `NOTICE` agree on Apache-2.0;
2. verify wheel and sdist contain the declared license files;
3. generate or verify the SBOM from the accepted dependency closure;
4. compare runtime/container dependencies with the third-party inventory and authoritative upstream licensing;
5. identify newly added, removed, relicensed, vendored, or copied components;
6. resolve any incompatible or unknown obligation before publication;
7. preserve attribution/NOTICE material required by dependencies and this project;
8. record the exact source revision and artifact identities used for the review; and
9. repeat transaction-specific ownership/title review when acquisition diligence requires evidence beyond repository declarations.

No automated scanner, SBOM generator, or assistant may convert an unknown licensing/ownership result into approval. Licensing evidence is one release/acquisition authority alongside security, quality, provenance, independent review, and operational acceptance.

## Change control

A change to outbound license, copyright ownership, provenance statement, dependency license classification, or required third-party notice is a material governance change. It requires explicit review, synchronized updates to package metadata/`LICENSE`/`NOTICE`/this document where applicable, release-impact assessment, and a CHANGELOG entry when user or buyer obligations change.

Do not silently relicense the project through a package-metadata edit or dependency upgrade. Do not remove NOTICE material merely because a build tool permits it.

## Evidence boundaries

- **IMPLEMENTED-ON-PROTECTED-MAIN:** Apache-2.0 package metadata plus root `LICENSE` and `NOTICE` exist on the current protected baseline.
- **ACTIVE-PR:** this canonical licensing/IP authority and its machine-checkable acquisition contract remain part of the documentation PR until protected integration.
- **Release-specific evidence:** SBOM contents, exact dependency versions, package-file inclusion, and upstream license verification must be regenerated/rechecked for the actual release candidate.
- **External/legal evidence:** employment/assignment agreements, transaction representations, trademark/patent analysis, and other title evidence are outside the repository and must not be invented here.

## References

Apache Software Foundation. (2004). *Apache License, Version 2.0*. https://www.apache.org/licenses/LICENSE-2.0

Python Packaging Authority. (2026). *Writing your pyproject.toml: License and license-files metadata*. Python Packaging User Guide. https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

OpenSSF. (n.d.). *Supply-chain Levels for Software Artifacts (SLSA)*. https://slsa.dev/
