# Remote batch recovery redaction — RED evidence

## Exact failing head

`be303cd27f094878d56e909a0f6c748fec1f5492`

Base SHA:

`3dbd37a372cd5f1898dab6f0096a7ed0e001493e`

## Hosted failure

GitHub Actions CI run `30976923588` executed the pull-request merge ref for the
exact test head. Python 3.10, 3.12, and 3.14 all failed only the new lifecycle
recovery regression. Python 3.12 job `92212753145` reported:

```text
FAILED tests/test_remote_batch_error_redaction.py::test_invalid_provider_identifier_is_redacted_from_recovery_error

{'batch_id': 'tenant-private/prompt-bearing-provider-id'} != {'batch_id': None}

1 failed, 304 passed, 3 deselected
Process completed with exit code 1.
```

The failing test supplied an unsupported provider-controlled batch identifier
after a simulated successful provider operation. The prior implementation copied
that raw value into `GatewayError.response_data` and chained the underlying
`ValidationError`, so sensitive provider content could enter operator errors,
logs, traces, or exception-reporting systems.

## Required green behavior

- validation occurs before any custom lifecycle recorder or PostgreSQL write;
- an unsupported provider-generated batch identifier is absent from structured
  recovery evidence;
- no exception cause exposes the rejected value;
- the evidence retains operation, phase, endpoint alias, observation order, and
  bounded error type;
- valid provider identifiers remain available when an independent persistence
  failure occurs; and
- the complete non-integration suite, 100% production statement/branch coverage,
  and 100% public-docstring gates pass.
