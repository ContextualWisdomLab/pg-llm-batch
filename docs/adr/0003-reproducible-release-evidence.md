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
The acceptance path therefore pins the build frontend to `uv` 0.12.3 and the
backend requirement to `uv_build==0.12.7`. The exact frontend can use its
compatible bundled backend, while external PEP 517 frontends are constrained to
the same backend version instead of silently selecting a later patch release.

The artifact verifier must fail on a third directory entry without materializing
an unbounded output directory. Because directory iteration order is not a stable
evidence source, count failures must not embed whichever filenames happened to
appear in the bounded sample.

The canonical evidence writer runs against pull-request-controlled workspace
paths. Rejecting a symlink and then later opening the same pathname is a
CWE-367 time-of-check/time-of-use boundary: a same-UID process can rename a
checked parent and put a symlink at its former pathname before temporary-file
creation. Repeating a lexical check, shortening the interval, or resolving the
pathname does not bind later operations to the object that was checked.

## Decision

Every release-relevant pull request runs a read-only acceptance workflow that:

1. checks out the exact pull-request head with persisted credentials disabled;
2. derives `SOURCE_DATE_EPOCH` from that exact commit;
3. creates two clean source trees from the same Git object;
4. performs two clean exact-head builds with the exact `uv` 0.12.3 frontend and
   `uv_build==0.12.7` backend contract;
5. reads at most three output-directory entries, requires exactly one wheel and
   one source distribution, and uses a fixed filesystem-order-independent
   diagnostic for missing or extra counts;
6. verifies regular non-symlink files, expected distribution/version identity,
   byte size, and streaming SHA-256 equality;
7. serializes one bounded canonical `release-manifest.json` payload before any
   filesystem mutation;
8. fails closed on unsupported platforms unless Python exposes the required
   descriptor-relative operations, `O_DIRECTORY`, `O_NOFOLLOW`, and no-follow
   status inspection;
9. opens the filesystem root or current directory, then walks or creates every
   parent component relative to a held directory descriptor using
   `O_DIRECTORY` and `O_NOFOLLOW`;
10. inspects the final destination without following a link and permits only an
    absent or regular file;
11. creates the temporary entry relative to the final parent descriptor with
    exclusive creation, `O_NOFOLLOW`, mode `0600`, and close-on-exec where
    available;
12. writes the payload, synchronizes the file, performs the atomic replacement
    with descriptor-relative `os.rename()`, and then synchronizes the final
    parent directory;
13. removes only the temporary entry created by the current invocation if a
    later write or replacement step fails; and
14. retains only the completed manifest for 14 days as review evidence.

New evidence directories request mode `0700`. Errors use bounded operation
categories and do not include manifest contents, source files, credentials,
environment variables, provider identifiers, resolved external targets, or
arbitrary operating-system exception text.

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
- Missing and extra artifact-count failures produce stable evidence even when
  filesystem iteration order changes.
- Parent traversal, direct or nested symlinks, and concurrent lexical parent
  replacement cannot redirect a write that is anchored to held directory
  descriptors.
- The temporary file and destination replacement remain in the originally
  opened final parent even when another process changes its pathname during the
  operation.
- Synchronizing the file and final parent directory gives operators explicit
  evidence of both byte and directory-entry durability boundaries.
- The function does not reserve or preserve the human-readable lexical pathname
  after the function returns. Another same-UID process may rename directories or
  entries later; callers requiring post-return ownership must enforce a separate
  workspace-isolation boundary.
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

### Include sampled filenames in extra-artifact count failures

Rejected because the verifier intentionally stops after the third entry and the
bounded sample depends on filesystem iteration order. A fixed count diagnostic
is sufficient to fail closed and preserves deterministic incident evidence.

### Repeat lexical symlink checks immediately before use

Rejected because the filesystem object can still change after the check. This
narrows but does not remove the CWE-367 interval and creates a false security
claim.

### Resolve the destination with `Path.resolve()` or `realpath()`

Rejected because resolution follows links and produces another mutable pathname.
It also changes the contract from refusing links to accepting their targets.

### Descriptor-relative no-follow traversal and rename

Selected because openat-style operations bind component lookup to held directory
objects and renameat-style replacement keeps source and destination in that
opened final directory. POSIX explicitly defines these interfaces to avoid path
replacement races.

### Fall back to the predecessor pathname writer on unsupported platforms

Rejected. Silent fallback would make the security property platform-dependent
while preserving the same success signal. Unsupported platforms receive one
fixed fail-closed error instead.

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

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*
(Version 4.20). https://cwe.mitre.org/data/definitions/367.html

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
