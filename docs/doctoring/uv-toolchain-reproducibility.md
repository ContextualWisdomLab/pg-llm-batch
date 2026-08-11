# Deterministic uv toolchain selection

## Status and scope

This doctoring record applies to the repository-owned Python dependency, lock, test, and package-build toolchain. It does not change pg-llm-batch runtime semantics, package dependencies, PostgreSQL state, provider behavior, or release authority. The repository root `uv.toml` is the tool-version authority for commands executed through the reviewed `astral-sh/setup-uv` action and for compatible local uv invocations.

## Incident and root cause

The protected-main workflow pinned the `astral-sh/setup-uv` GitHub Action by immutable commit but did not constrain the uv executable selected by that action. With no root `uv.toml` and no `required-version` in `pyproject.toml`, setup-uv logged that it was **falling back to latest** and resolved uv 0.12.3 at execution time. That made package locking, test-environment materialization, and package builds depend on mutable release discovery even when repository source and action commit were unchanged.

The causal boundary is tool selection, not dependency resolution inside `uv.lock`: an immutable action pin fixes the action implementation, while a separate uv version contract fixes the executable the action installs. The package lock remains independently governed by `uv.lock` and the existing `uv lock --check` gate.

## Chosen correction

The root configuration contains exactly:

```toml
required-version = "==0.12.3"
```

The exact PEP 440 equality requirement is deliberate. `setup-uv` discovers this root setting after checkout when no explicit workflow version overrides it, and uv itself rejects execution when its version does not satisfy `required-version`. CI therefore resolves the reviewed uv release from repository source rather than from the moving latest release.

This change does not edit `.github/workflows/ci.yml`, which is independently owned by the exact-source-governance work. It preserves the immutable setup-uv action pin, lock freshness, Python 3.10/3.12/**Python 3.14** tests, package build, coverage/docstring, security, SAST, and container gates.

## Test-first evidence

The first regression head added `tests/test_uv_toolchain_pin.py` before the configuration file existed. CI failed exactly because `uv.toml` was absent; the same run visibly logged the setup-uv latest-release fallback and installed uv 0.12.3. Adding the exact root requirement then made CI, Security Scan, and SAST succeed, and setup-uv logged that it found version 0.12.3 in `uv.toml` before installation.

A second RED documentation contract, `tests/test_uv_toolchain_documentation.py`, required this rationale, version authority, update procedure, rollback path, Python 3.14 preservation, and primary-source references before this doctoring file existed. That failure is intentional development evidence and does not count as final passing evidence for the later head.

## Update procedure

A uv upgrade is a reviewed toolchain change, not ordinary latest-version drift.

1. Review the candidate uv release and relevant setup-uv/uv release notes and security information from authoritative Astral sources.
2. Change the exact `required-version` value in `uv.toml` in a bounded pull request.
3. Do not change `uv.lock` merely because the tool version changed; regenerate it only when dependency or lock-format semantics actually require a reviewed lock change.
4. Run the full permanent CI matrix, including Python 3.10, 3.12, and Python 3.14, 100% owned production statement/branch coverage, public docstrings, Ruff, lock freshness, clean package build, Compose/container builds, Security Scan, and SAST.
5. Inspect setup-uv evidence to confirm it resolved the exact reviewed version from root `uv.toml`, not from a latest-version fallback or an unrelated workflow override.
6. Revalidate any release reproducibility or provenance evidence whose build-tool identity depends on uv before publication.

## Rollback and recovery

If a reviewed uv upgrade causes lock, test, build, packaging, or platform regressions, rollback means restoring the last known accepted exact `required-version` and rerunning the same gates on the resulting source. Do not recover by deleting `uv.toml`, broadening the specifier, or selecting `latest`; those actions recreate the mutable tool-selection boundary.

If Astral distribution of the pinned executable is temporarily unavailable, treat that as tool-distribution infrastructure failure. Do not silently select another uv version to make CI pass. A deliberate version replacement requires the update procedure above and fresh evidence.

## Security and supply-chain implications

Pinning the executable reduces unreviewed toolchain drift but is not an artifact-authentication or provenance claim. The immutable action commit, setup-uv download behavior, runner controls, uv executable version, `uv.lock`, source revision, built artifacts, SBOM, and provenance are separate evidence classes. A green uv-version contract does not replace dependency vulnerability scanning, package reproducibility, or publication attestation.

## APA 7 references

Astral Software. (2026). *setup-uv: Advanced version configuration*. GitHub. https://github.com/astral-sh/setup-uv/blob/main/docs/advanced-version-configuration.md

Astral Software. (2026). *Using uv in GitHub Actions*. uv documentation. https://docs.astral.sh/uv/guides/integration/github/

Astral Software. (2026). *uv settings: required-version*. uv documentation. https://docs.astral.sh/uv/reference/settings/#required-version
