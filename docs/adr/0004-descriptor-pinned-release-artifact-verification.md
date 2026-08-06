# ADR 0004: Descriptor-pinned release artifact verification

- **Status:** Proposed
- **Date:** 2026-08-06
- **Decision owners:** ContextualWisdomLab maintainers

## Context

The reproducible-release gate previously bounded directory enumeration and
rejected symlinks before hashing, but it later reopened artifact pathnames and
queried size through pathname metadata. A same-UID concurrent process could
replace a checked entry, redirect a parent component, add an unexpected entry,
or mutate a regular file between check and use. The resulting manifest could
therefore describe bytes or directory state different from the objects that
passed validation.

This is a CWE-367 time-of-check/time-of-use boundary. Repeating pathname checks,
calling `resolve()`, or shortening the interval does not bind subsequent
operations to the checked filesystem objects. Release evidence is a buyer-facing
supply-chain control and must fail closed rather than preserve a success signal
on runtimes that cannot provide the required object binding.

## Decision

The release artifact verifier shall:

1. require descriptor-relative `os.open`, descriptor-based `os.scandir`,
   `O_DIRECTORY`, `O_NOFOLLOW`, and `O_NONBLOCK` support before reading an
   artifact;
2. reject `..` components;
3. start absolute traversal from an opened `/` descriptor and relative traversal
   from an opened `.` descriptor;
4. open each release-directory component relative to the currently held
   descriptor with `O_DIRECTORY | O_NOFOLLOW`;
5. enumerate at most three entries from the held final directory descriptor,
   record each bounded entry's device, inode, file type, size, modification time,
   and change time without following symlinks, require exactly one wheel and one
   source distribution, and preserve fixed filesystem-order-independent count
   diagnostics;
6. validate expected distribution and version from the bounded names before
   opening artifacts;
7. open each artifact relative to the held directory descriptor with
   `O_NOFOLLOW | O_NONBLOCK`, require a regular file from `fstat`, require its
   identity to equal the corresponding initial directory-entry identity, and
   never reopen it by pathname;
8. stream SHA-256 with bounded `os.read` calls and derive byte size from that same
   open file description;
9. compare device, inode, file type, size, modification time, and change time
   before and after streaming, rejecting any drift;
10. re-enumerate the same held directory descriptor after both artifact reads and
    compare the complete bounded name-and-identity snapshot, rejecting membership
    changes and same-name inode replacements; and
11. expose only bounded operation-category errors, never arbitrary operating-
    system exception text or resolved external targets.

The verifier remains read-only and does not publish, sign, attest, approve, or
authorize reuse of pull-request artifacts. Descriptor binding protects the
verification interval; governed runner and workspace isolation remain required
because a same-UID process can modify objects after the function returns.

## Consequences

- Parent symlinks and parent traversal cannot redirect artifact lookup.
- Artifact replacement after enumeration is rejected whether it becomes a
  symlink or another regular file with the same name and bytes.
- Size and digest always describe the same open file description.
- In-place mutation detected through byte-count or stable-inode metadata drift
  invalidates the evidence.
- Added, removed, or same-name-replaced directory entries invalidate the bounded
  artifact set before a manifest is accepted.
- FIFO, socket, device, directory, and symlink substitutions cannot block or
  masquerade as regular release artifacts.
- Unsupported platforms receive one fail-closed capability error. No pathname fallback is permitted.
- Version `0.1.0` remains unchanged and this decision does not publish a release.

## Alternatives considered

### Repeat `is_symlink()` and `is_file()` immediately before hashing

Rejected because the target can change after either check and before open.

### Resolve every path to an absolute canonical pathname

Rejected because canonicalization follows links and returns another mutable
pathname rather than a held filesystem object.

### Open artifacts once but keep pathname-based parent traversal

Rejected because a parent component can be replaced before the artifact open.
All component lookup must be relative to held directory descriptors.

### Compare only final directory names

Rejected because a regular file can be replaced by a new inode with the same
name and bytes. The final bounded snapshot must include object identity.

### Permit a compatibility fallback

Rejected because identical success output with weaker platform-dependent
semantics would make acquisition and release evidence misleading.

## Rollback

Rollback must stop release acceptance, revert the implementation and its
security, documentation, and concurrency contracts together, and rerun the full
integrated prerequisite stack. Pathname check-then-use verification must not be
advertised as an equivalent fallback. No manifest produced during rollback may
be used for publication, provenance, or acquisition evidence.

## References (APA 7th edition)

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*
(Version 4.20). https://cwe.mitre.org/data/definitions/367.html

Python Software Foundation. (2026). *os—Miscellaneous operating system
interfaces*. Python 3.14 documentation. Retrieved August 6, 2026, from
https://docs.python.org/3.14/library/os.html

The Open Group. (2024). *open, openat—Open file*. In *The Open Group Base
Specifications Issue 8, IEEE Std 1003.1-2024*.
https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html
