# OpenTelemetry operation contract — GREEN evidence

## Test-first lineage

The behavioral contract was introduced first at exact head
`59f7fa9d07550223084d04c44fcb31ca4c80637e`. GitHub Actions CI run
`30974219174` failed on Python 3.10, 3.12, and 3.14 because
`pg_llm_batch.observability` did not yet exist. The detailed failure is retained
in `2026-08-05-opentelemetry-operations-red.md`.

## Verified implementation head

Exact implementation and documentation head before this evidence-only commit:

`566daf824d89cf4484d422d68d35e5bd03325790`

Base SHA:

`3dbd37a372cd5f1898dab6f0096a7ed0e001493e`

GitHub Actions CI run `30974600196` completed successfully on that exact head.
The same-head `SAST Semgrep` run `30974600163` and `Security Scan` run
`30974600145` also completed successfully.

## Verification results

The CI matrix and release-oriented quality gates produced the following fresh
results:

- Python 3.10 unit tests: success;
- Python 3.12 unit tests: success;
- Python 3.14 unit tests: success;
- component and PostgreSQL container builds: success;
- Ruff: `All checks passed!`;
- public docstring coverage: `100.0%` with a `100.0%` threshold;
- production statement and branch coverage: `100.00%`;
- total coverage: 1,226 statements with zero misses and 324 branches with zero
  partial branches;
- `pg_llm_batch/observability.py`: 55 statements with zero misses;
- test result: `248 passed, 3 deselected`;
- lockfile freshness: success;
- source distribution and wheel builds: success, with
  `pg_llm_batch/observability.py` included in both artifacts;
- SAST Semgrep: success; and
- Security Scan: success.

## Contract proven

The deterministic test doubles prove that all six public client operations emit
one bounded span, operation-count measurement, and duration measurement. They
also prove that failures preserve the original exception object, that optional
OpenTelemetry imports remain lazy, and that a private endpoint alias is absent
from emitted telemetry. The production module has complete beginner-readable
public docstrings and keeps the ordinary `BatchAPIClient` free of a mandatory
OpenTelemetry dependency.

## Final exact-head rule

This document is an evidence-only commit and therefore changes the pull-request
head. It does not substitute for final-head verification. Merge remains
prohibited until every required CI, security, review, provenance, branch
protection, and independent-approval gate succeeds again on the exact final
head.
