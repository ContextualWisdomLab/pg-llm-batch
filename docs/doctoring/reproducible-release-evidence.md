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
artifact, so it fails without enumerating an unbounded build directory. Missing
or extra artifact counts use one fixed, filesystem-order-independent diagnostic.
When exactly two entries have the wrong artifact kinds, the verifier may include
only their sorted, bounded names. The filename must identify the expected
distribution and project version. Extra files, missing files, symlinks, wrong
versions, wrong distribution names, or byte mismatches fail closed.

SHA-256 is calculated in bounded chunks. The verifier compares only:

- artifact filename;
- byte size; and
- SHA-256 digest.

On success, it serializes canonical JSON for
`release-evidence/release-manifest.json` before changing the filesystem. The
writer then anchors the output to a directory descriptor rather than trusting a
previously checked pathname:

1. an absolute destination starts from an opened filesystem-root descriptor and
   a relative destination starts from an opened current-directory descriptor;
2. every missing parent is created relative to the currently held descriptor
   with requested mode `0700`;
3. every parent is opened descriptor-relative with `O_DIRECTORY`,
   `O_NOFOLLOW`, and close-on-exec where available;
4. the destination is inspected without following links and must be absent or a
   regular file;
5. the owned temporary entry is exclusively created relative to the final
   parent descriptor with `O_NOFOLLOW` and requested mode `0600`;
6. the writer flushes and calls `fsync()` on the temporary file;
7. descriptor-relative `os.rename()` performs the atomic replacement inside the
   same opened final parent; and
8. a second `fsync()` synchronizes the final parent directory entry.

The writer fails closed on an unsupported platform before creating an evidence
directory. It requires descriptor-relative support for open, directory creation,
status inspection, unlink, and rename; no-follow status inspection; and both
`O_DIRECTORY` and `O_NOFOLLOW`. It does not silently fall back to the predecessor
check-then-use implementation.

If a write, file synchronization, or atomic replacement fails after this call
created its temporary entry, the writer removes only that owned temporary entry
relative to the held final parent descriptor. It never removes a pre-existing
entry. A cleanup failure is a separate fail-closed condition. After a successful
rename, a final-parent synchronization failure reports that the manifest name is
already replaced but the durability boundary was not confirmed.

The manifest records its schema version, distribution name, project version,
exact source commit, `SOURCE_DATE_EPOCH`, artifact names, byte sizes, and
digests. It never records package contents, source files, environment variables,
credentials, network headers, provider data, arbitrary operating-system error
text, resolved external path targets, or build logs.

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
   or non-reproducible artifact; stops after the third directory entry when
   rejecting an unexpected artifact count; and emits the same fixed count
   diagnostic regardless of filesystem iteration order.
6. Confirm the runtime reports all descriptor-relative and no-follow capabilities
   required by the writer. An unsupported platform must fail before
   `release-evidence` is created.
7. Confirm parent traversal is rejected and each parent is opened through a held
   directory descriptor with `O_DIRECTORY` and `O_NOFOLLOW`.
8. Confirm the destination is absent or regular, the owned temporary is created
   exclusively with requested mode `0600`, and no pre-existing temporary entry
   is removed.
9. Confirm one `fsync()` covers manifest bytes before the atomic replacement and
   another covers the final parent directory after descriptor-relative
   `os.rename()`.
10. Download the bounded manifest only when diligence requires independent
    digest inspection.
11. Reject a queued, pending, cancelled, skipped, absent, predecessor-head, or
    stale-base result.

A successful manifest does not prove who built the package. It is not a digital
signature, SBOM, SLSA provenance statement, release approval, or publication
record. A future release workflow must generate provenance for the integrated
release commit, use independently reviewed release authority, and separately
satisfy SBOM, vulnerability, package-index, and rollback requirements.

The descriptor binding protects operations during this function call. It does
not reserve the lexical pathname after the function returns. Another same-UID
process may later rename the directory or manifest; an environment requiring
post-return ownership must isolate the workspace and process authority
separately.

## Failure triage

### Artifact set failure

The verifier deliberately stops after a third entry because the exact two-artifact
contract is already disproven. Missing or extra counts produce a fixed diagnostic
without sampled filenames, so filesystem iteration order cannot change operator
evidence. Exactly two wrong-kind entries may be reported only after bounded
sorting. Do not relax the exact two-artifact contract to accommodate caches,
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

### Unsupported platform failure

Confirm the runner is a Unix platform whose Python runtime lists `os.open`,
`os.mkdir`, `os.stat`, `os.unlink`, and `os.rename` in `os.supports_dir_fd`, lists
`os.stat` in `os.supports_follow_symlinks`, and exposes `O_DIRECTORY` plus
`O_NOFOLLOW`. Move the acceptance job to a governed compatible runner. Do not
patch around the error or add a pathname fallback.

### Parent path failure

Inspect the destination lexically. Remove `..` components. Replace no symlink
with its target; instead, create a regular governed evidence directory. A
non-directory component, permission failure, or race that changes a component
must remain fail closed. Do not reuse a manifest from a predecessor head.

### Destination or temporary failure

The destination may be absent or an existing regular file. A directory, device,
FIFO, socket, or symlink is invalid. Any pre-existing temporary name is invalid
and must be investigated before manual removal. The function cleans only the
owned temporary created by its own invocation.

### Atomic replacement or synchronization failure

A replacement failure leaves the previous regular destination unchanged and
attempts to remove the owned temporary. A file-sync failure occurs before
replacement. A final-parent `fsync()` failure occurs after the manifest name was
atomically replaced; treat the output as unaccepted evidence and rerun on healthy
storage from a new exact-head job.

### Rollback

The rollback for this security slice is to stop the Release Acceptance workflow,
revert the descriptor-relative writer and its exact tests as one reviewed change,
and rerun the complete prerequisite stack. The predecessor lexical symlink
checks are weaker and must not be advertised or used as an equivalent secure
fallback. Do not publish, attest, or reuse any manifest produced while the
rollback is in progress.

## Security and acquisition rationale

The gate narrows buyer diligence from “the package built once” to “two clean
builds of the same reviewed source and exact build toolchain produced the same
named bytes.” Bounded artifact enumeration prevents malformed output directories
from turning a fail-closed validation decision into unbounded verifier memory
use. Fixed count diagnostics prevent filesystem ordering from changing incident
evidence. Descriptor-relative no-follow traversal removes the static parent
check’s CWE-367 time-of-check/time-of-use interval: later lookup, temporary-file
creation, cleanup, and rename are bound to opened directory objects. Explicit
file and directory synchronization makes the durability decision observable.
This supports repeatable incident reconstruction and future SLSA v1.2 provenance
without mixing pull-request validation with release authority. Top-level
permissions remain read-only, credentials are not persisted, action sources are
immutably pinned, and the evidence payload is bounded.

## References (APA 7)

Astral. (n.d.). *The uv build backend*. uv documentation. Retrieved August 6,
2026, from https://docs.astral.sh/uv/concepts/build-backend/

GitHub. (n.d.). *Using artifact attestations to establish provenance for builds*.
GitHub Docs. Retrieved August 6, 2026, from
https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*
(Version 4.20). https://cwe.mitre.org/data/definitions/367.html

Python Packaging Authority. (n.d.). *Binary distribution format*.
Python Packaging User Guide. Retrieved August 6, 2026, from
https://packaging.python.org/en/latest/specifications/binary-distribution-format/

Python Packaging Authority. (n.d.). *Source distribution format*.
Python Packaging User Guide. Retrieved August 6, 2026, from
https://packaging.python.org/en/latest/specifications/source-distribution-format/

Python Software Foundation. (2026). *os—Miscellaneous operating system
interfaces*. Python 3.14 documentation. Retrieved August 6, 2026, from
https://docs.python.org/3.14/library/os.html

Reproducible Builds. (n.d.). *SOURCE_DATE_EPOCH specification*. Retrieved
August 6, 2026, from https://reproducible-builds.org/specs/source-date-epoch/

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification,
version 1.2*. https://slsa.dev/spec/v1.2/

The Open Group. (2024). *open, openat—Open file*. In *The Open Group Base
Specifications Issue 8, IEEE Std 1003.1-2024*.
https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html

The Open Group. (2024). *rename, renameat—Rename file*. In *The Open Group Base
Specifications Issue 8, IEEE Std 1003.1-2024*.
https://pubs.opengroup.org/onlinepubs/9799919799/functions/rename.html
