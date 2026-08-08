# Descriptor-bound release manifest writes

- **Status:** Approved by the standing autonomous development directive
- **Date:** 2026-08-06
- **Dependency:** PR #55 exact head `3660bb9edd6351a9c02d9507f08ed647ddbf0d3a`

## Problem

PR #55 makes reproducible-release evidence bounded, canonical, atomic, and
symlink-aware. Its manifest writer still checks parent paths before opening the
temporary file by pathname. A same-UID concurrent process can rename a checked
parent directory and replace its lexical path with a symlink between the check
and `os.open()`. The temporary file and atomic replacement can then operate
through the replacement path. This is a time-of-check/time-of-use boundary
rather than a missing static symlink check.

The release acceptance job is read-only and does not expose publication or
attestation authority, but buyer-facing evidence must not be writable outside
its selected directory merely because the workspace path changes between calls.

## Decision

Replace pathname-based manifest creation with a descriptor-relative writer on
platforms that provide the required POSIX primitives.

1. Serialize canonical JSON before filesystem mutation.
2. Reject an empty final filename, `.` or `..`, and any parent traversal
   component.
3. Open the filesystem root for absolute destinations or the current directory
   for relative destinations.
4. Walk each parent component relative to a held directory descriptor. Create a
   missing directory with mode `0700`, then open it with `O_DIRECTORY` and
   `O_NOFOLLOW` before closing the previous descriptor.
5. Inspect the destination relative to the final parent descriptor without
   following links. Permit replacement only of an existing regular destination;
   reject every non-regular destination.
6. Create the temporary file relative to the held descriptor with
   `O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW`, mode `0600`, and close-on-exec
   where available. Exclusive creation rejects every pre-existing temporary
   entry atomically.
7. Write, flush, and `fsync()` the temporary file. Atomically replace the
   destination with descriptor-relative `os.rename()` source and destination
   names, then `fsync()` the final parent directory.
8. If a failure occurs after this invocation created the temporary file, remove
   only that descriptor-relative entry. Never remove a pre-existing entry.
9. Close every descriptor on every path.

The writer fails closed with `ReleaseEvidenceError` when descriptor-relative
open, directory creation, no-follow status inspection, unlink, or rename support,
`O_DIRECTORY`, or `O_NOFOLLOW` is unavailable. It does not silently fall back to
the predecessor check-then-use implementation.

## Scope boundary

This slice secures manifest output path selection and atomic replacement. It
does not redesign artifact discovery or hashing, publish a release, grant OIDC
or package permissions, create a new workflow, or claim protection against a
malicious same-UID process that changes a path after the function returns. The
existing read-only workflow, bounded evidence payload, exact-head checkout, and
stacked-base rules remain unchanged.

## Alternatives considered

### Keep the lexical precheck and narrow the race window

Rejected. Repeating `Path.is_symlink()` or moving it closer to `os.open()` does
not bind the checked object to the object later used.

### Resolve the destination with `Path.resolve()` or `realpath()`

Rejected. Resolution follows links and produces another pathname that can be
changed before use. It also changes the contract from refusing links to
accepting their targets.

### Descriptor-relative traversal and replacement

Selected. POSIX `openat()`-style operations bind each lookup to a held directory
descriptor, and `renameat()`-style replacement keeps both names in that same
opened directory. Unsupported platforms fail closed rather than receiving a
weaker security claim.

## Error and privacy contract

Errors identify only the fixed release-evidence operation and a bounded reason
class. They do not include canonical manifest contents, source files,
credentials, environment variables, provider identifiers, arbitrary exception
text, or resolved external path targets.

## Test strategy

Strict red-green-refactor TDD adds deterministic tests before implementation.
The principal RED test swaps the manifest parent for a symlink immediately when
temporary-file creation begins. The predecessor implementation writes outside
the selected directory; the descriptor-relative implementation must keep all
bytes in the originally opened directory and leave the symlink target untouched.

Additional tests cover:

- absolute and relative destination success;
- replacement of an existing regular manifest;
- direct and nested parent symlink rejection;
- `..`, empty, and non-regular destination rejection;
- pre-existing regular, symlink, and directory temporary entries;
- unavailable descriptor/no-follow primitives failing closed;
- owned-temporary cleanup after write or replacement failure;
- bounded errors for root-open, directory-create, destination-stat, temporary
  creation, text-stream creation, file-sync, rename, cleanup, and directory-sync
  failures;
- file and parent-directory synchronization;
- descriptor closure on success and failure;
- 100% production statement, branch, and public-docstring coverage.

## Operational and acquisition consequences

The manifest writer no longer relies on mutable workspace pathname identity
between validation, creation, and replacement. The evidence remains review-only,
bounded, and unauthoritative for publication, while its write target is anchored
to a directory object rather than a previously checked string path.

## References (APA 7th edition)

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*
(Version 4.20). https://cwe.mitre.org/data/definitions/367.html

Python Software Foundation. (2026). *os—Miscellaneous operating system
interfaces*. Python 3.14 documentation. Retrieved August 6, 2026, from
https://docs.python.org/3.14/library/os.html

The Open Group. (2024). *open, openat—Open file*. In *The Open Group Base
Specifications Issue 8, IEEE Std 1003.1-2024*.
https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html

The Open Group. (2024). *rename, renameat—Rename file*. In *The Open Group Base
Specifications Issue 8, IEEE Std 1003.1-2024*.
https://pubs.opengroup.org/onlinepubs/9799919799/functions/rename.html
