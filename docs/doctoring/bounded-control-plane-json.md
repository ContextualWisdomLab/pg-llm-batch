# Bounded control-plane JSON responses

## Decision

Files and Batches control-plane responses must be decoded through an explicit,
small, decoded-byte budget before UTF-8 or JSON parsing. The client must not call
`ClientResponse.json()` or `ClientResponse.text()` for these responses because
those convenience APIs can materialize the complete provider-controlled body
before the package can apply its own resource policy.

The default control-plane budget is **1 MiB per HTTP response**. It is separate
from the larger provider output/error-file budget because ordinary upload,
creation, status, and cancellation metadata should remain small. A host may
raise the limit only for a reviewed provider contract.

## Threat model

A malicious, compromised, misconfigured, or malfunctioning OpenAI-compatible
gateway can return a very large response to any of the following operations:

- Files API upload;
- batch creation;
- batch status;
- batch cancellation.

Without a decoded-byte limit, the process can allocate memory proportional to
the complete response before validating whether the response is a JSON object.
This is a resource-exhaustion boundary in a long-running worker and an
availability risk for both standalone deployments and services that embed the
client as an MSA module.

MITRE classifies failure to control allocation or maintenance of a limited
resource as uncontrolled resource consumption. Its examples explicitly contrast
unbounded whole-body reads with predetermined byte limits. Aiohttp exposes
`ClientResponse.content` as the streaming response-body interface and documents
a 64 KiB default read buffer, which matches the package's existing bounded file
reader.

## Contract

`BatchAPIClient` adds:

```python
DEFAULT_MAX_CONTROL_RESPONSE_BYTES = 1 * 1024 * 1024

BatchAPIClient(
    postgres_dsn,
    credentials,
    max_control_response_bytes=DEFAULT_MAX_CONTROL_RESPONSE_BYTES,
)
```

The value must be a positive, non-boolean integer. Invalid values fail during
construction with a field-specific `ValidationError`.

Every control-plane response is processed in this order:

1. inspect a non-negative integer `content_length` only as an early rejection
   signal;
2. require a callable `response.content.iter_chunked` stream;
3. read chunks while enforcing the actual decoded-byte total;
4. reject the first chunk that would exceed the active limit;
5. decode strict UTF-8;
6. call `json.loads()` exactly once;
7. require a JSON object;
8. apply the endpoint's existing HTTP-status contract.

`Content-Length` is not authoritative because it can be absent, malformed, or
smaller than the decoded stream. The observed decoded-byte total is the final
resource boundary.

## Error data minimization

An oversized response raises `GatewayError` with only bounded operational
metadata:

```json
{
  "limit_bytes": 1048576,
  "declared_bytes": 2000000,
  "bytes_read": 0
}
```

A mid-stream rejection reports bytes accepted before the rejected chunk. Invalid
UTF-8 and malformed/non-object JSON retain only exception class or response type.
Provider content, previews, digests, URLs, headers, aliases, credentials, and
resource identifiers are excluded.

A response adapter without `content.iter_chunked` fails closed. The client never
falls back to `response.json()` or `response.text()` because either fallback
would remove the bounded-read guarantee.

## Compatibility

Successful public endpoint dictionaries remain unchanged. Existing HTTP status,
invalid-JSON, and non-object JSON exception categories remain unchanged. Output
and error-file downloads continue to use the independent
`max_download_bytes` limit.

Custom response adapters and test doubles must implement the same bounded byte
stream contract as aiohttp. This is an intentional security requirement rather
than a compatibility fallback.

## Verification

Permanent tests cover:

- positive-integer constructor validation and the one-MiB default;
- declared oversize rejection before stream iteration;
- actual decoded-byte overflow despite an understated header;
- exact-limit success;
- strict UTF-8 rejection;
- malformed and non-object JSON;
- one JSON decode after bounded reading;
- explicit proof that `response.json()` and `response.text()` are never called;
- upload, creation, status, and cancellation paths;
- independent provider-file download limits;
- missing bounded-stream fail-closed behavior;
- Python 3.10, 3.12, and 3.14 compatibility;
- production statement, branch, and docstring coverage at 100%.

## References

Aiohttp Project. (2026). *Client reference (aiohttp 3.14 documentation)*.
https://docs.aiohttp.org/en/v3.14.0/client_reference.html

MITRE. (2026). *CWE-400: Uncontrolled resource consumption* (Version 4.20).
https://cwe.mitre.org/data/definitions/400.html
