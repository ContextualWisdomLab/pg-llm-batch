# Component image reproducibility and Debian snapshot authority

## Status

**ACTIVE-PR.** This document describes the bounded component-image supply-chain change under review. It must not be read as protected-main behavior until the corresponding pull request is integrated and revalidated.

## Problem boundary

Pinning the Python and `uv` base-image digests does not by itself make the final component image reproducible when `apt-get update` resolves runtime packages from mutable Debian mirrors. The package set can change while the pg-llm-batch source commit and base-image digests remain unchanged.

The component runtime needs only `libpq5` for PostgreSQL client libraries and `curl` for the existing container health probe. The reviewed solution therefore keeps those runtime requirements while moving APT index resolution to Debian's timestamp-addressed snapshot archive.

## Selected contract

The component Dockerfile uses the same explicit snapshot instant for the main Debian archive and Debian Security archive. Debian snapshot semantics map a requested timestamp to the latest imported archive state at or before that instant, so a fixed URL represents a stable archive state rather than a moving mirror. The selected source currently uses `20260812T000000Z` for `trixie`, `trixie-updates`, and `trixie-security`.

`check-valid-until=no` is scoped only to these intentionally frozen snapshot sources. Debian documents that historical snapshots can otherwise be rejected after their Release metadata expires. This setting is not a general TLS, signature, or repository-validation bypass and must not be copied to ordinary moving repositories.

Routine builds MUST NOT perform `apt-get upgrade`. Dependency refresh occurs by a reviewed update of the snapshot timestamp followed by component-image build, package/security scanning, and the normal exact-source acceptance gates. A security advisory is therefore handled by advancing the declared snapshot input, not by silently changing the package graph beneath an unchanged source revision.

## Verification and evidence

The repository contract requires:

1. one fixed timestamp across every component-image Debian snapshot source;
2. no `deb.debian.org` or `security.debian.org` runtime package source in the component Dockerfile;
3. no unconstrained distribution upgrade during an ordinary build;
4. continued installation of only the required `libpq5` and `curl` runtime packages at this boundary;
5. a successful clean component-image build from the exact source head; and
6. security/SAST/SBOM/provenance evidence to remain separate from the reproducibility claim. A reproducible vulnerable input is still vulnerable and must be refreshed.

The current scope makes the **APT repository state** reproducible. It does not claim byte-for-byte OCI image reproducibility by itself: layer timestamps, builder metadata, package post-install behavior, and other image-construction inputs require their own deterministic evidence. Existing wheel/sdist reproducibility and release-evidence contracts remain independent.

## Recovery and rollback

If a selected snapshot cannot build, lacks a required package, or fails current security acceptance, do not fall back to a mutable mirror inside the same source revision. Select another reviewed timestamp, record the change in source control, and reacquire all affected checks. Rollback is the inverse source change to a previously reviewed timestamp and must likewise rebuild and revalidate the image; no cached image is accepted merely because an older source revision once passed.

## References

Debian Project. (n.d.). *snapshot.debian.org*. Retrieved August 13, 2026, from https://snapshot.debian.org/

Supply-chain Levels for Software Artifacts. (2026). *SLSA specification v1.2: Build track basics*. https://slsa.dev/spec/v1.2/build-track-basics

Reproducible Builds. (2017). *SOURCE_DATE_EPOCH specification* (Revision 1.1). https://reproducible-builds.org/specs/source-date-epoch/
