# Release artifact descriptor verification

This doctoring note defines the operator contract for secure artifact identity
verification inside the read-only reproducible-release gate.

## Threat boundary

The release output directories, their parent components, directory membership,
and artifact entries are untrusted concurrent filesystem state. A same-UID
process may rename a checked entry, replace a parent with a symlink, add an
unexpected file, truncate or overwrite an artifact, or substitute a special file
between a pathname check and later use.

The verifier therefore treats pathname checks as insufficient. It binds lookup,
enumeration, and artifact reads to held file descriptors for the complete
verification interval. This addresses the CWE-367 check-before-use weakness; it
does not claim protection after the verifier closes its descriptors and returns.
Governed runner and workspace isolation remain separate required controls.

## Required runtime capabilities

Before reading an artifact, the verifier requires:

- `O_DIRECTORY`, `O_NOFOLLOW`, and `O_NONBLOCK`;
- descriptor-relative `os.open` support; and
- descriptor-based `os.scandir` support.

An unsupported runtime fails with the fixed capability error before artifact
bytes are read. Operators must move the job to a governed compatible Unix runner.
Do not add or enable a pathname fallback.

## Verification sequence

For each clean build directory:

1. Reject a lexical `..` component.
2. Open `/` for an absolute path or `.` for a relative path.
3. Walk every component using `os.open(..., dir_fd=current_fd)` with
   `O_DIRECTORY | O_NOFOLLOW`.
4. Enumerate at most three names from the held final directory descriptor.
5. Require exactly one `.whl` and one `.tar.gz`; missing or extra counts use one
   fixed diagnostic without sampled names.
6. Validate distribution and version from each bounded name.
7. Open each name relative to the held directory with
   `O_NOFOLLOW | O_NONBLOCK` and require a regular file from `fstat`.
8. Stream bytes in 1 MiB chunks with `os.read`, calculating SHA-256 and byte
   count from the same open file description.
9. Compare device, inode, file type, size, modification time, and change time
   before and after the stream; reject any change.
10. Re-enumerate the same directory descriptor and require the exact initial
    bounded name-and-identity snapshots, including device, inode, file type,
    size, modification time, and change time, so same-name replacement is
    rejected.
11. Compare the two clean-build records by filename, size, and digest.

The verifier closes every artifact and directory descriptor on both success and
failure. Diagnostics identify only the failed contract category and never include
arbitrary operating-system exception text, credentials, file contents, resolved
external targets, or unbounded directory listings.

## Operator verification

Confirm on the exact current head and current integrated base that:

- Python 3.10, 3.12, and 3.14 unit suites pass;
- production statement and branch coverage and public docstrings are 100%;
- a symlinked parent component fails before artifact access;
- relative parent traversal fails before root or current-directory traversal;
- artifact replacement after directory enumeration is rejected by no-follow
  open or stable-identity validation;
- an in-place write during streaming invalidates the evidence;
- an added or removed directory entry invalidates the exact two-artifact set;
- unsupported flags, relative-open support, and descriptor-scan support each
  independently fail closed;
- enumeration remains bounded to three entries;
- Release Acceptance builds both clean trees and writes only the bounded
  canonical manifest; and
- queued, pending, cancelled, skipped, absent, predecessor-head, or stale-base
  checks are not counted as evidence.

## Failure triage

### Capability failure

Inspect the runner platform and Python `os.supports_dir_fd` and `os.supports_fd`
sets. Move to the governed Linux runner rather than changing the verifier.

### Directory path failure

Remove `..` components. Replace no symlink with its target; create a regular
workspace directory under the governed checkout instead. A missing,
non-directory, permission-denied, or concurrently replaced component must remain
fail closed.

### Artifact type or open failure

The output must contain ordinary regular files. Investigate symlinks, FIFOs,
sockets, devices, directories, or concurrent replacement. Do not copy or rename
a substitute into place after the build and reuse an older check.

### Artifact changed during verification

Treat this as workspace compromise, competing writer activity, or a broken build
step. Preserve bounded job evidence, terminate competing writers, produce a new
exact head when source changes are needed, and rerun from clean build trees.
Never accept a digest collected before the mutation.

### Directory changed during verification

Find and remove the process writing caches, logs, attestations, or other outputs
inside the release build directory. Those products belong outside the exact
wheel-and-sdist directory. Rerun both clean builds.

## Rollback

Stop Release Acceptance before reverting this security boundary. Revert the
implementation, tests, ADR, doctoring, architecture, agent contracts, and
CHANGELOG together through review. The predecessor pathname verifier is not an
equivalent secure mode. Do not publish, attest, sign, or reuse any artifact or
manifest produced while the rollback is incomplete.

## Acquisition rationale

Descriptor-pinned verification lets a buyer distinguish a deterministic
artifact identity decision from a mutable-path best effort. The evidence remains
bounded, reproducible, least-privileged, and separate from publication authority.
It strengthens future SBOM and provenance workflows without allowing a
pull-request check to become a release credential.

## References (APA 7)

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*
(Version 4.20). https://cwe.mitre.org/data/definitions/367.html

Python Software Foundation. (2026). *os—Miscellaneous operating system
interfaces*. Python 3.14 documentation. Retrieved August 6, 2026, from
https://docs.python.org/3.14/library/os.html

The Open Group. (2024). *open, openat—Open file*. In *The Open Group Base
Specifications Issue 8, IEEE Std 1003.1-2024*.
https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html
