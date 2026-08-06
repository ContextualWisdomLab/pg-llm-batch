# ADR 0003: Reproducible release evidence before publication

- **Status:** Proposed
- **Date:** 2026-08-06
- **Decision owners:** ContextualWisdomLab maintainers

## Context

The ordinary CI workflow proves tests, coverage, docstrings, lint, packaging, and
container construction. It does not prove that two clean exact-head builds emit
the same Python distribution bytes. A buyer, operator, or release reviewer
therefore cannot distinguish a reproducible package from an artifact affected by
ambient timestamps, a dirty source tree, hidden generated files, or a changed
build input.

Artifact provenance and publication are separate trust decisions. A signed
attestation can accurately describe a non-reproducible build, while a
reproducibility check does not authenticate the builder or publish an artifact.
Both properties matter, but they require different permissions and review gates.

PEP 517 build-system requirements are resolved independently from ordinary
project dependencies: build-system requirements are not pinned by `uv.lock`.
The acceptance path therefore pins the build frontend to `uv` 0.12.1 and the
backend requirement to `uv_build==0.12.1`. The exact frontend can use its
compatible bundled backend, while external PEP 517 frontends are constrained to
the same backend version instead of silently selecting a later patch release.

## Decision

Every release-relevant pull request runs a read-only acceptance workflow that:

1. checks out the exact pull-request head with persisted credentials disabled;
2. derives `SOURCE_DATE_EPOCH` from that exact commit;
3. creates two clean source trees from the same Git object;
4. performs two clean exact-head builds with the exact `uv` 0.12.1 frontend and
   `uv_build==0.12.1` backend contract;
5. requires one wheel and one source distribution in each result;
6. verifies regular non-symlink files, expected distribution/version identity,
   byte size, and streaming SHA-256 equality;
7. writes one canonical bounded `release-manifest.json`; and
8. retains only that manifest for 14 days as review evidence.

The pull-request workflow has only `contents: read`. It does not publish,
does not attest, does not request an OpenID Connect token, and does not receive
package or attestation write permissions. Publication remains a future,
separately reviewed release workflow. That workflow must bind its provenance to
the integrated release commit, use trusted publishing, and satisfy independent
approval, branch protection, exact-head security, packaging, and release gates.

## Consequences

- Non-deterministic package bytes fail before a tag or release is considered.
- Build frontend and backend patch selection cannot drift between governed or
  external PEP 517 builds without an explicit reviewed source change.
- Artifact identity evidence is machine-readable, bounded, and free of source
  payloads, credentials, provider data, and environment dumps.
- The manifest is evidence for review, not a signature, SBOM, provenance
  attestation, release authorization, or substitute for independent approval.
- A future release workflow may consume the same verified artifact set and add
  SLSA provenance and SPDX SBOM attestations, but must not reuse a pull-request
  artifact as release evidence without proving its exact integrated source.
- Version `0.1.0` remains unchanged and no release is published by this decision.

## Alternatives considered

### Build only once

Rejected because one successful build proves package validity, not deterministic
artifact identity.

### Permit a compatible backend patch range

Rejected for the governed release contract because an external PEP 517 frontend
could resolve a later compatible `uv_build` patch independently of `uv.lock`.
Patch upgrades remain straightforward, but they require an explicit reviewed pin
change and fresh exact-head evidence.

### Upload both complete build directories from every pull request

Rejected because complete artifacts increase retention, disclosure, and artifact
substitution risk without improving the bounded equality decision.

### Grant attestation permissions to the pull-request workflow

Rejected because untrusted pull-request verification does not need write-capable
identity or attestation permissions. Least privilege keeps validation separate
from release authority.

## References (APA 7th edition)

Astral. (n.d.). *The uv build backend*. uv documentation. Retrieved August 6,
2026, from https://docs.astral.sh/uv/concepts/build-backend/

GitHub. (n.d.). *Using artifact attestations to establish provenance for builds*.
GitHub Docs. Retrieved August 6, 2026, from
https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds

Python Packaging Authority. (n.d.). *Source distribution format*.
Python Packaging User Guide. Retrieved August 6, 2026, from
https://packaging.python.org/en/latest/specifications/source-distribution-format/

Reproducible Builds. (n.d.). *SOURCE_DATE_EPOCH specification*. Retrieved
August 6, 2026, from https://reproducible-builds.org/specs/source-date-epoch/

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification,
version 1.2*. https://slsa.dev/spec/v1.2/
