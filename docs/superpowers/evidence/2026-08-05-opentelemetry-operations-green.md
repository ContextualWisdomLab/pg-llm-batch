# OpenTelemetry operation contract — GREEN evidence

## Test-first lineage

The feature and every subsequently discovered safety boundary were introduced as
failing hosted tests before the corresponding production change:

1. Initial API contract, exact head
   `59f7fa9d07550223084d04c44fcb31ca4c80637e`: CI run `30974219174`
   failed on Python 3.10, 3.12, and 3.14 because
   `pg_llm_batch.observability` did not exist.
2. Runtime provider isolation, exact head
   `0ef14b0d615b82c73b7f2b58ecda6467d988059f`: CI run `30974859878`
   proved that tracer or metric failures could replace a successful return value
   or mask the original provider exception.
3. Exception-event privacy, exact head
   `d0aa02101c31d25d897e4a7838404d39a5f4fcce`: CI run `30975210502`
   failed with one regression because `record_exception()` copied the original
   secret-bearing exception object into the span.
4. Span-context privacy, exact head
   `357a815706da3b5698eddfcc265393c0486debc6`: CI run `30975506925`
   failed because the context manager received the exception type, object, and
   traceback instead of null exit arguments.
5. Provider cancellation and construction isolation, exact head
   `5ebe9b13e2a6731764d02abfbf68f407589657f5`: CI run `30975688015`,
   Python 3.12 job `92209087983`, failed with two intended regressions. An
   `asyncio.CancelledError` raised by the provider path bypassed the previous
   `Exception` handler and left the span open, while a metric-instrument creation
   error prevented client construction.
6. Telemetry-originated cancellation isolation, exact head
   `9f5065ac6131ee0aaf7a1b16c1ebae659444bc0e`: CI run `30976127911`,
   Python 3.12 job `92210369257`, failed with three intended regressions and
   reported `3 failed, 254 passed, 3 deselected`. A tracer cancellation skipped
   the provider call, a metric cancellation replaced a successful result, and a
   metric cancellation masked the provider's original cancellation object.
7. Process-control propagation, exact head
   `ecfcf610236b6ee87d506e40a7ce333f3d347ab6`: CI run `30976286658`,
   Python 3.12 job `92210853057`, failed with one intended regression and
   reported `1 failed, 257 passed, 3 deselected`. Catching all
   `BaseException` at the telemetry-only boundary incorrectly swallowed an
   arbitrary non-cancellation process-control exception.

The detailed initial failure is retained in
`2026-08-05-opentelemetry-operations-red.md`. Later RED runs remain visible in
the immutable GitHub Actions history and are summarized here so the final
safety contract is auditable without treating post-implementation tests as
TDD evidence.

## Verified implementation head

Exact production and test head:

`1bfd55dff128a722c7b3c4a613ca906f78a0f02f`

Base SHA:

`3dbd37a372cd5f1898dab6f0096a7ed0e001493e`

The following same-head GitHub Actions runs succeeded:

- CI run `30976370842`;
- SAST Semgrep run `30976370815`; and
- Security Scan run `30976370846`.

## Verification results

The CI matrix and release-oriented quality gates produced the following fresh
results on the verified implementation head:

- Python 3.10 unit tests: success;
- Python 3.12 unit tests: success;
- Python 3.14 unit tests: success;
- component and PostgreSQL container builds: success;
- Ruff: `All checks passed!`;
- public docstring coverage: `100.0%` with a `100.0%` threshold;
- production statement and branch coverage: `100.00%`;
- total coverage: 1,252 statements with zero misses and 330 branches with zero
  partial branches;
- `pg_llm_batch/observability.py`: 81 statements with zero misses and six
  branches with zero partial branches;
- test result: `258 passed, 3 deselected`;
- lockfile freshness: success;
- source distribution and wheel builds: success, with
  `pg_llm_batch/observability.py` included in both artifacts;
- SAST Semgrep: success; and
- Security Scan: success.

## Contract proven

Deterministic tracer, span-context, meter, and instrument doubles prove that:

- all six public client operations emit one bounded span, operation-count
  measurement, and duration measurement when providers are available;
- emitted attributes contain only the bounded operation name, outcome, and
  canonical error class;
- endpoint aliases, remote identifiers, tenant values, payloads, exception
  objects, exception messages, and tracebacks do not enter custom telemetry;
- span contexts receive null exception exit arguments on provider failures and
  provider task cancellation;
- ordinary telemetry-provider failures and telemetry-originated
  `asyncio.CancelledError` cannot skip the provider operation, replace a
  successful result, or mask the original exception or cancellation;
- arbitrary non-cancellation process-level `BaseException` control flow is not
  swallowed by the telemetry boundary;
- metric-instrument construction failures fall back to local no-op instruments
  without disabling the client;
- provider-originated `asyncio.CancelledError` is classified, measured when
  possible, and re-raised unchanged; and
- the ordinary `BatchAPIClient` retains no mandatory OpenTelemetry dependency.

The production module and its fail-open helpers have complete
beginner-readable public docstrings, 100% statement coverage, and 100% branch
coverage.

## Final exact-head rule

This evidence update changes the pull-request head and does not substitute for
final-head verification. Merge remains prohibited until every required CI,
security, review, provenance, branch-protection, and independent-approval gate
succeeds again on the exact final head and base.
