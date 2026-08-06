# Reproducible release evidence

This doctoring note defines the operator-visible contract for the read-only
release acceptance gate. The gate detects non-deterministic Python distribution
artifacts before maintainers consider a version bump, tag, publication, or
provenance attestation.

## Evidence boundary

The workflow checks out the exact pull-request head and refuses a checkout SHA
mismatch. It derives `SOURCE_DATE_EPOCH` from the checked-out commit, exports a
fixed hash seed, timezone, and locale, and creates two clean source trees with
`git archive`.

PEP 517 build-system requirements are resolved separately from ordinary project
dependencies: build-system requirements are not pinned by `uv.lock`. The
governed acceptance path therefore uses the exact `uv` 0.12.1 frontend and
requires `uv_build==0.12.1`. The exact uv frontend can use its compatible bundled
backend, and external PEP 517 frontends must resolve the same backend version.
Any frontend or backend patch upgrade requires an explicit reviewed source
change and fresh exact-head evidence.

Each build directory must contain exactly one wheel and exactly one source distribution.
Every artifact must be a regular non-symlink file. The verifier reads at most
three directory entries: a third entry is sufficient evidence of an unexpected
artifact, so it fails without enumerating an unbounded build directory. The
filename must identify the expected distribution and project version. Extra
files, missing files, symlinks, wrong versions, wrong distribution names, or
byte mismatches fail closed.

SHA-256 is calculated in bounded chunks. The verifier compares only:

- artifact filename;
- byte size; and
- SHA-256 digest.

On success, it writes canonical JSON to
`release-evidence/release-manifest.json`. The manifest additionally records its
schema version, distribution name, project version, exact source commit, and
`SOURCE_DATE_EPOCH`. It never records package contents, source files,
environment variables, credentials, network headers, provider data, or build
logs.

The workflow preserves only `release-manifest.json` for 14 days. Uploaded
artifacts are review evidence and are not authorized release inputs.

## Stacked pull request verification

For a stacked pull request, exact-head release acceptance proves only that the
head branch produces reproducible artifacts. Repository integration evidence
must also come from a fresh GitHub-generated merge commit that combines that
exact head with the current stacked base. A workflow result generated against a
predecessor base is stale-base evidence even when the head SHA has not changed.

After changing or advancing the prerequisite branch, synchronize the dependent
pull request and confirm the new merge commit names the expected head and base
before accepting CI, security, coverage, packaging, or container results. Once
the prerequisite merges, retarget the dependent pull request to integrated main
and rerun every required gate. Never reuse a successful stacked-base check as
final main-branch merge evidence.

## Operator verification

1. Open the exact-head **Release Acceptance / Reproducible wheel and sdist**
   check.
2. Confirm the checkout assertion names the current pull-request head.
3. Confirm the workflow uses `uv` 0.12.1 and `uv_build==0.12.1` from the exact
   reviewed source.
4. Confirm both clean builds complete under the same `SOURCE_DATE_EPOCH`.
5. Confirm the verifier reports no missing, extra, symlinked, identity-mismatched,
   or non-reproducible artifact and stops after the third directory entry when
   rejecting an unexpected artifact set.
6. Download the bounded manifest only when diligence requires independent digest
   inspection.
7. Reject a queued, pending, cancelled, skipped, absent, predecessor-head, or
   stale-base result.

A successful manifest does not prove who built the package. It is not a digital
signature, SBOM, SLSA provenance statement, release approval, or publication
record. A future release workflow must generate provenance for the integrated
release commit, use independently reviewed release authority, and separately
satisfy SBOM, vulnerability, package-index, and rollback requirements.

## Failure triage

### Artifact set failure

Inspect the first three build-directory entries reported by the bounded scan.
The verifier deliberately stops after a third entry because the exact two-artifact
contract is already disproven. Do not relax that contract to accommodate caches,
logs, or local evidence files; route those files outside the build directories.

### Identity failure

Confirm `project.name` and `project.version` in `pyproject.toml` match the wheel
and source-distribution filenames. Do not rename artifacts after build.

### Build-toolchain failure

Confirm the workflow frontend remains exactly `uv` 0.12.1 and the project
backend requirement remains exactly `uv_build==0.12.1`. Do not treat
`uv.lock` as evidence for PEP 517 build-system requirements. A deliberate
upgrade must change both governed pins, rerun the packaging and release tests,
and produce new exact-head evidence.

### Reproducibility failure

Compare the two bounded manifest records locally. Common causes include build
timestamps, generated files, unordered archive inputs, ambient source-tree
state, or a backend that ignores `SOURCE_DATE_EPOCH`. Fix the build input or
backend determinism and rerun from a new exact head. Never copy the first build
over the second or compare only extracted contents.

### Manifest path failure

The manifest writer refuses a symlink destination or an existing temporary
path. Remove only a verified local stale temporary file and rerun. Do not follow
or replace an untrusted symlink.

## Security and acquisition rationale

The gate narrows buyer diligence from “the package built once” to “two clean
builds of the same reviewed source and exact build toolchain produced the same
named bytes.” Bounded artifact enumeration prevents malformed output directories
from turning a fail-closed validation decision into unbounded verifier memory
use. This supports repeatable incident reconstruction and future SLSA v1.2
provenance without mixing pull-request validation with release authority.
Top-level permissions remain read-only, credentials are not persisted, action
sources are immutably pinned, and the evidence payload is bounded.

## References (APA 7)

Astral. (n.d.). *The uv build backend*. uv documentation. Retrieved August 6,
2026, from https://docs.astral.sh/uv/concepts/build-backend/

GitHub. (n.d.). *Using artifact attestations to establish provenance for builds*.
GitHub Docs. Retrieved August 6, 2026, from
https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds

Python Packaging Authority. (n.d.). *Binary distribution format*.
Python Packaging User Guide. Retrieved August 6, 2026, from
https://packaging.python.org/en/latest/specifications/binary-distribution-format/

Python Packaging Authority. (n.d.). *Source distribution format*.
Python Packaging User Guide. Retrieved August 6, 2026, from
https://packaging.python.org/en/latest/specifications/source-distribution-format/

Reproducible Builds. (n.d.). *SOURCE_DATE_EPOCH specification*. Retrieved
August 6, 2026, from https://reproducible-builds.org/specs/source-date-epoch/

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification,
version 1.2*. https://slsa.dev/spec/v1.2/
