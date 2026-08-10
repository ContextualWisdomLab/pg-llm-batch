# ADR: First-class OpenTelemetry optional dependency and live conformance

- **Status:** PLANNED — Issue #107
- **Documentation maturity:** ACTIVE-PR #93 until this record reaches protected main
- **Implementation dependency:** resolve only after the active release/package-metadata owner #57 and operation-span status owner #106 integrate or are superseded

## Context

`OpenTelemetryBatchAPIClient` is a documented public integration surface, while protected-main package metadata does not expose an OpenTelemetry optional extra. Operators must currently discover and reproduce an external dependency constraint manually. Deterministic tests also use bounded doubles for most telemetry behavior, so package metadata cannot itself state the supported `opentelemetry-api` range and the permanent suite does not yet prove one real optional-API success/failure span boundary.

This is a packaging and compatibility gap, not a reason to make OpenTelemetry mandatory for ordinary `BatchAPIClient` users or to move SDK/exporter authority into pg-llm-batch.

## Drivers

- make the optional observability integration discoverable and reproducible through package metadata;
- keep the base package dependency set unchanged;
- preserve host ownership of OpenTelemetry SDK/exporter/global-provider configuration;
- bind documentation, lock/refresh policy, built artifacts, and live conformance to one supported API range;
- preserve the privacy boundary from ACTIVE-PR #106: failure span status is Error without a description, success remains Unset, and finite `error.type` remains the package-owned error vocabulary;
- keep missing optional support actionable only when an OpenTelemetry-specific constructor is selected.

## Alternatives considered

### A. Make `opentelemetry-api` a mandatory base dependency

Rejected. Base batch operation does not need telemetry and standalone/embedded consumers must remain free to omit OpenTelemetry entirely.

### B. Keep a doctoring-only `pip install` instruction

Rejected as the final commercial contract. Human instructions can drift from wheel metadata, lock policy, and tested compatibility.

### C. Add a first-class optional package extra plus live optional-API conformance

Chosen. A named extra provides a machine-readable installation contract while retaining a dependency-free base observability boundary for users that do not opt in.

## Decision

When Issue #107 becomes executable, add a clearly named optional extra for the reviewed `opentelemetry-api` range. The ordinary dependency set must remain unchanged. Package metadata, README/API/doctoring guidance, lock/refresh policy, wheel/sdist metadata, and tests must agree on that range.

The permanent validation suite must install the optional extra in a clean environment and exercise `OpenTelemetryBatchAPIClient.from_global_provider()` with the real API for at least one success and one propagated-failure operation. Success must leave span status at the OpenTelemetry default Unset state. Failure must receive Error status without a provider/caller exception message in the status description, and the existing finite `error.type`/privacy behavior must remain unchanged. Base-package installation without the extra must continue to import and use ordinary `BatchAPIClient` without OpenTelemetry.

## Consequences and non-goals

- This decision does not require or configure an OpenTelemetry SDK/exporter globally.
- It does not claim every future OpenTelemetry release is compatible.
- It does not change provider transport, persistence, credentials, schema, retry, or release authority.
- It does not make ACTIVE-PR #106 shipped; #106 must settle before #107 implementation composes its span-status contract.
- It does not modify package metadata while #57 is the active release/package-metadata owner.

## Failure and recovery

If the declared optional range becomes incompatible, dependency refresh must fail closed through package/conformance gates rather than silently widening the supported range. Rollback restores the last reviewed optional range and corresponding lock/artifact metadata without changing the base dependency set. Missing optional support must remain a bounded actionable error only on the OpenTelemetry-specific construction path.

## Verification and acceptance

The implementation is acceptable only when all of the following are true on the final exact source:

1. base installation has no OpenTelemetry dependency;
2. the named optional extra installs the declared supported `opentelemetry-api` range;
3. wheel/sdist metadata, documentation, and lock/refresh policy agree;
4. a real-API success span remains Unset;
5. a real-API propagated failure is Error with no sensitive description and retains finite `error.type` behavior;
6. missing optional support is bounded to the OpenTelemetry-specific constructor;
7. Python 3.10, 3.12, and 3.14 pass;
8. owned production statement/branch coverage and public docstrings remain 100%; and
9. packaging, security/SAST, SBOM/provenance, review, and release-acceptance gates required by live policy pass.

## References

OpenTelemetry Authors. (2026). *OpenTelemetry Python API: Trace*. OpenTelemetry. https://opentelemetry-python.readthedocs.io/en/latest/api/trace.html

Python Packaging Authority. (2026). *Writing your pyproject.toml: Dependencies and requirements*. Python Packaging User Guide. https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#dependencies-and-requirements

Python Software Foundation. (2025). *PEP 621 – Storing project metadata in pyproject.toml*. Python Enhancement Proposals. https://peps.python.org/pep-0621/
