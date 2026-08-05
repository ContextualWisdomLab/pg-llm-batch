# OpenTelemetry operation contract — RED evidence

## Exact pre-implementation head

`59f7fa9d07550223084d04c44fcb31ca4c80637e`

## Hosted verification

GitHub Actions CI run `30974219174` executed the pull-request merge ref for the
exact test head against base `3dbd37a372cd5f1898dab6f0096a7ed0e001493e`.
The Python 3.10, 3.12, and 3.14 unit-test matrix jobs all failed during test
collection. The Python 3.14 job `92204802735` recorded the intended missing
production capability:

```text
ERROR collecting tests/test_opentelemetry_operations.py
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient
ModuleNotFoundError: No module named 'pg_llm_batch.observability'
Interrupted: 1 error during collection
Process completed with exit code 2.
```

The test introduced the required API and behavior before implementation. The
failure is therefore caused by the absent observability module rather than an
implemented path returning an unexpected value.

The quality job also reported one independent test-lint defect: an unused
`typing.Callable` import. That import was removed without changing the behavioral
contract before green verification.

## Required green behavior

- all six public client operations emit one bounded span, count, and duration;
- success and error outcomes are distinguished without dynamic identifiers;
- failures record a canonical exception type and re-raise the original object;
- the base client retains no mandatory OpenTelemetry dependency;
- global provider resolution is lazy and produces an actionable missing-package
  error;
- production statement, branch, and public-docstring coverage remain 100%.
