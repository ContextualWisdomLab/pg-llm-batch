# Remote batch identity reconciliation RED evidence

## Risk captured

A durable status poll requested for one validated remote batch identifier could
accept a provider payload containing another syntactically valid identifier.
Because the prior implementation used `setdefault("id", requested_id)`, a
present mismatched provider identifier survived normalization and could reach an
injected lifecycle recorder or PostgreSQL under the wrong compound identity.
That behavior risked cross-batch state contamination and made the trusted
requested identifier unavailable in bounded reconciliation evidence.

## Exact failing head

`5ae4463b38f6eec5bf4fcccf8d52d6cc6a725c2a`

Base SHA:

`3dbd37a372cd5f1898dab6f0096a7ed0e001493e`

## Regression test

`tests/test_remote_batch_identity_contract.py::test_poll_rejects_mismatched_provider_batch_identity`

The test requests `batch-requested`, returns `batch-other` from the deterministic
provider response, and requires the durable client to:

- raise a persistence-phase `GatewayError`;
- expose only `batch-requested` in bounded recovery metadata;
- suppress the raw mismatched provider identifier from the exception and its
  cause;
- avoid calling the lifecycle recorder.

## Hosted RED result

GitHub Actions CI run `30978399259`, Python 3.14 job `92217374521`, failed for
the intended reason:

```text
FAILED tests/test_remote_batch_identity_contract.py::test_poll_rejects_mismatched_provider_batch_identity
Failed: DID NOT RAISE GatewayError
1 failed, 305 passed, 3 deselected
Process completed with exit code 1.
```

The same run's coverage job failed because the required regression was still
red. Container builds succeeded, and the exact red head's SAST Semgrep and
Security Scan workflows succeeded, so the observed behavioral failure was not
hidden by an unrelated build or scanner failure.

## Required green behavior

A status response whose present `id` differs from the validated requested batch
identifier must fail before any lifecycle recorder or PostgreSQL write. Public
recovery evidence must retain only the trusted requested identifier, preserve
the observation order and bounded error type, expose no raw mismatched value,
and leave the original durable projection unchanged.
