# Provider output retention policy

## Purpose

`BatchAPIClient.create_batch_job()` can optionally request a bounded provider-side lifetime for generated Batch API output and error files. The option is deliberately explicit: callers that omit it retain the historical provider-default payload, while callers that choose a lifetime must supply an exact integer from 3,600 through 2,592,000 seconds.

The package validates this value before credential resolution or provider I/O. Invalid booleans, non-integer values, and out-of-range integers fail locally with bounded validation evidence. Rejected caller values are not copied into exported validation details.

## Provider contract

When `output_expires_after_seconds` is supplied, the client emits:

```json
{
  "output_expires_after": {
    "anchor": "created_at",
    "seconds": 3600
  }
}
```

OpenAI documents `created_at` as the supported anchor and accepts lifetimes from one hour through thirty days. The anchor refers to creation of the generated output/error file rather than creation of the batch itself. Because pg-llm-batch targets OpenAI-compatible providers as well as OpenAI, this field remains opt-in rather than a provider-neutral default; compatible gateways that do not implement the extension may reject a caller-selected policy.

## Assurance boundary

Remote provider expiration is not equivalent to local PostgreSQL retention, legal erasure, deletion of the uploaded input file, deletion of generated output files before expiry, or deletion of copies already downloaded by a caller. Those controls remain separately governed. This slice only makes the provider output/error-file lifetime explicit, bounded, auditable at request construction, and backward-compatible when omitted.

The public request path preserves the existing input-file identifier, endpoint, metadata, credential, transport, retry, and result contracts. It does not introduce a background deletion worker or new durable persistence.

## Verification

`tests/test_provider_file_retention.py` proves:

- a one-hour lifetime is serialized exactly;
- the documented thirty-day upper bound is accepted;
- omission preserves the historical request body;
- booleans, strings, floats, values below one hour, and values above thirty days fail before credential/provider I/O; and
- the validation error identifies only the package-owned field boundary.

The test-only RED head demonstrated the missing keyword on Python 3.10, 3.12, and 3.14 before the production implementation was added. Final acceptance requires the unchanged implementation head to pass the repository's full exact-source quality, security, coverage, package, provenance, review, and live-policy gates.

## Rollback

Rollback is an ordinary revert of the optional request parameter and its tests/documentation. Rollback restores reliance on provider defaults and therefore removes caller control over this remote artifact-lifetime boundary; it does not delete already-created remote artifacts.

## Reference

OpenAI. (2026). *Batch | OpenAI API reference*. https://platform.openai.com/docs/api-reference/batch/object
