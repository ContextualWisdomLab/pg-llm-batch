# PEP 639 License Metadata Migration Design

## Context

The package currently declares:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]

[project]
license = { text = "Apache-2.0" }
```

Current setuptools emits a deprecation warning for the legacy `project.license` table. The Python Packaging User Guide states that PEP 639 replaces the table form with:

- a string SPDX expression in `project.license`; and
- explicit `project.license-files` glob patterns for legal files shipped in distribution archives.

The guide also identifies setuptools 77.0.3 as the first setuptools release supporting the standardized PEP 639 fields. Keeping a lower backend floor of 68 would therefore advertise a configuration that some allowed build backends cannot interpret.

This is a release-readiness gap rather than cosmetic cleanup. Package consumers, vulnerability scanners, legal review systems, procurement tooling, and artifact repositories depend on normalized `License-Expression` and `License-File` core metadata. The current build warning also states that the legacy form will stop being supported after the announced compatibility window.

## Goals

- Replace the deprecated license table with the SPDX expression `Apache-2.0`.
- Declare both repository legal files, `LICENSE` and `NOTICE`, through `project.license-files`.
- Raise the minimum setuptools build backend to the first documented PEP 639-compatible version.
- Verify both source configuration and installed distribution metadata on every supported Python version.
- Verify the built wheel and source distribution continue to contain both legal files.
- Remove the setuptools license deprecation warning from normal package builds.
- Retain the current package name, version, runtime dependencies, CLI, and Apache-2.0 licensing.
- Preserve 100% production statement, branch, and docstring coverage.

## Non-goals

- Changing the project license.
- Publishing a release in the same pull request.
- Adding a new packaging backend.
- Adding license classifiers, which are deprecated when using `License-Expression` metadata.
- Changing runtime dependency resolution.
- Replacing `NOTICE` with generated attribution output.

## Approaches considered

### 1. PEP 639 expression plus explicit legal files — selected

Use:

```toml
[build-system]
requires = ["setuptools>=77.0.3", "wheel"]

[project]
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
```

This directly follows the current packaging specification. Literal paths are valid license-file glob patterns, each exists in the repository, and both files are legally relevant to Apache-2.0 distribution.

The installed editable distribution and built wheel are expected to expose:

```text
License-Expression: Apache-2.0
License-File: LICENSE
License-File: NOTICE
```

### 2. Change only the license value

Use `license = "Apache-2.0"` but rely on setuptools' automatic license-file discovery.

This removes the immediate table warning, but it leaves the legal-file inclusion contract backend-dependent and implicit. A future backend change or discovery-default change could silently omit `NOTICE`.

### 3. Keep the legacy table until its removal deadline

This avoids a metadata diff today but retains a known build warning and makes a future release dependent on a time-sensitive migration. It also denies downstream tooling the standardized `License-Expression` field.

### 4. Pin a current setuptools version exactly

An exact build-backend pin would maximize reproducibility but increases maintenance and may block security fixes. The repository already uses a lower-bound policy for build tools. The documented compatibility floor is sufficient for this metadata contract, while lock and artifact verification protect the project output.

## Selected contract

### Source metadata

`pyproject.toml` must contain all of the following:

```toml
requires = ["setuptools>=77.0.3", "wheel"]
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
```

It must not contain the legacy table form or a `License ::` classifier.

### Installed metadata

After `uv sync --locked`, `importlib.metadata.metadata("pg-llm-batch")` must report:

- exactly `Apache-2.0` for `License-Expression`;
- `LICENSE` and `NOTICE` as the complete `License-File` set; and
- no legacy free-text `License` value.

### Artifact contents

The wheel must include both legal files under its `.dist-info/licenses/` directory. The source distribution must include the root `LICENSE` and `NOTICE` files. Package construction remains part of the exact-head CI gate.

## Failure behavior

The change is fail-closed at build and test time:

- an unsupported backend floor fails the source contract;
- a missing legal file causes the PEP 639 glob contract or artifact verification to fail;
- missing or wrong installed metadata fails tests on Python 3.10, 3.12, and 3.14;
- a reintroduced legacy table or license classifier fails the source contract;
- package builds, lock verification, SAST, security scans, and container builds remain mandatory.

## Testing strategy

Add `tests/test_packaging_metadata.py` with two initial failing tests:

1. source configuration uses the PEP 639 string, explicit legal files, and compatible backend floor;
2. the installed editable distribution exposes normalized license expression and file metadata.

The tests intentionally use `importlib.metadata`, which is available across all supported Python versions, and simple source-contract assertions rather than adding a TOML parser solely for tests.

A one-shot implementation workflow will additionally inspect the generated wheel and source archive before deleting itself. Permanent CI continues to run the source and installed-metadata tests plus the package build.

## Documentation and changelog

`CHANGELOG.md` records the migration under `Unreleased / Changed`. README does not need a new user-facing section because the package license itself is unchanged and is already visible in the repository; the normalized artifact metadata is the externally relevant result.

## Release decision

This migration removes a known release warning and is a prerequisite for a clean future release, but it does not publish a version alone. Release publication remains gated on:

- all unreleased changes being reviewed as one coherent release;
- exact-head CI, SAST, security, package, and provenance evidence;
- an explicit version bump and dated changelog section;
- signed or attestable artifacts and a defined publication workflow.

## Standards basis

- PEP 639 and the Python Packaging User Guide define `project.license` as an SPDX expression string and `project.license-files` as legal-file glob patterns.
- The Python Packaging User Guide documents setuptools 77.0.3 as the first setuptools version supporting these fields.
- Apache-2.0 is a valid SPDX license identifier.
