# Batch endpoint path policy

The `endpoint` field submitted to an OpenAI-compatible Batch API is validated
before gateway credentials are resolved.

Accepted values are absolute API paths such as:

```text
/v1/chat/completions
/v1/embeddings
/v1/responses
/deployments/gpt-4o_2026/chat-completions
```

The contract permits 1–16 non-empty ASCII path segments and at most 256 total
characters. Segments may contain letters, digits, `.`, `_`, `~`, or `-`.

The client rejects:

- complete URLs and scheme-relative URLs;
- empty segments, trailing slashes, `.` or `..` traversal segments;
- queries, fragments, percent escapes, backslashes, controls, or whitespace;
- Unicode lookalike paths; and
- non-string or oversized values.

This contract prevents an application or configuration error from asking the
provider to batch an ambiguous or unintended resource. Validation happens before
API-key lookup, so rejected endpoints consume no gateway secret and make no HTTP
request.
