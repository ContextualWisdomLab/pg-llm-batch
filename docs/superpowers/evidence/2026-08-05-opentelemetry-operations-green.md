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
5. Cancellation and construction isolation, exact head
   `5ebe9b13e2a6731764d02abfbf68f407589657f5`: CI run `30975688015`,
   Python 3.12 job `92209087983`, failed with two intended regressions. An
   `asyncio.CancelledError` bypassed the `Exception` handler and left the span
   open, while a metric-instrument creation error prevented client
   construction.

The detailed initial failure is retained in
`2026-08-05-opentelemetry-operations-red.md`. Later RED runs remain visible in
the immutable GitHub Actions history and are summarized here so the final
safety contract is auditable without treating post-implementation tests as
TDD evidence.

## Verified implementation head

Exact production and test head:

`fa14df057ae9bb98eb5f8fcd30ec4c15647d6155`

Base SHA:

`3dbd37a372cd5f1898dab6f0096a7ed0e001493e`

The following same-head GitHub Actions runs succeeded:

- CI run `30975775870`;
- SAST Semgrep run `30975775766`; and
- Security Scan run `30975775764`.

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
- total coverage: 1,251 statements with zero misses and 330 branches with zero
  partial branches;
- `pg_llm_batch/observability.py`: 80 statements with zero misses and six
  branches with zero partial branches;
- test result: `254 passed, 3 deselected`;
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
- span contexts receive null exception exit arguments on both provider failures
  and task cancellation;
- tracer and metric runtime failures cannot skip the provider operation, replace
  a successful result, or mask the original exception;
- metric-instrument construction failures fall back to local no-op instruments
  without disabling the client;
- `asyncio.CancelledError` is classified, measured when possible, and re-raised
  unchanged; and
- the ordinary `BatchAPIClient` retains no mandatory OpenTelemetry dependency.

The production module and its fail-open helpers have complete
beginner-readable public docstrings, 100% statement coverage, and 100% branch
coverage.

## Final exact-head rule

This evidence update changes the pull-request head and does not substitute for
final-head verification. Merge remains prohibited until every required CI,
security, review, provenance, branch-protection, and independent-approval gate
succeeds again on the exact final head and base.
