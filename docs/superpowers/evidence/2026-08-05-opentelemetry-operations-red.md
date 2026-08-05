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

## Nested-operation dispatch RED

CodeRabbit identified that the real `wait_for_batch()` and `download_results()`
paths dynamically call `self.get_batch_status()`. The subclass override therefore
emitted an additional public `get_batch_status` span, counter measurement, and
duration measurement inside the outer caller operation.

The regression contract was committed before the production repair at exact head
`642f43eefa8e795f5debe9f28b5a77ed3fe806d8`. GitHub Actions CI run
`30976749340`, Python 3.10 job `92212230204`, executed the real parent dispatch
paths and reported:

```text
2 failed, 258 passed, 3 deselected

Left contains one more item: 'pg_llm_batch.get_batch_status'
FAILED tests/test_opentelemetry_nested_operations.py::test_parent_operation_suppresses_internal_status_poll_telemetry[wait_for_batch]
FAILED tests/test_opentelemetry_nested_operations.py::test_parent_operation_suppresses_internal_status_poll_telemetry[download_results]
Process completed with exit code 1.
```

This failure proves the prior implementation counted an internal status poll as
another caller-visible operation. The test does not replace either outer parent
method; it replaces only the provider-status boundary so dynamic dispatch remains
part of the exercised production path.

## Dynamic error-type RED

The initial privacy contract prevented exception messages and tracebacks from
entering telemetry but copied `type(error).__name__` into `error.type`. A caller
or provider can define an exception class at runtime, so that name can contain a
tenant identifier, secret-like value, or an unbounded set of dimensions.

The exact test-only head `d53e5223e69d63bb5b97fe94b7038468dbf77154`
constructed an exception class named
`Tenant42BearerTokenMustNotBecomeTelemetry` and required `_OTHER` in the span,
counter, and histogram while preserving the original exception object. GitHub
Actions CI run `30977814467` failed on Python 3.10, 3.12, and 3.14. The Python
3.12 job `92215533742` reported the intended single regression:

```text
1 failed, 260 passed, 3 deselected

expected: _OTHER
received: Tenant42BearerTokenMustNotBecomeTelemetry
FAILED tests/test_opentelemetry_privacy_contract.py::test_untrusted_exception_class_name_uses_bounded_fallback
Process completed with exit code 1.
```

This proves that the previous implementation exposed a caller-controlled class
name as custom telemetry and did not satisfy the predictable low-cardinality
`error.type` contract.

## Required green behavior

- all six caller-invoked public client operations emit one bounded span, count,
  and duration;
- internal public-method dispatch performed by an already observed outer
  operation does not emit a second caller-visible signal set;
- success and error outcomes are distinguished without dynamic identifiers;
- failures use a finite documented exact-type vocabulary and `_OTHER` for every
  unrecognized or caller-defined class;
- failures re-raise the exact original exception object;
- the base client retains no mandatory OpenTelemetry dependency;
- global provider resolution is lazy and produces an actionable missing-package
  error;
- production statement, branch, and public-docstring coverage remain 100%.
