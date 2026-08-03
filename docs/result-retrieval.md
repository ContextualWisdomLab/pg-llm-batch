# Batch result retrieval

`BatchAPIClient.download_results()` and the `retrieve` CLI command download every
terminal artifact exposed by the provider:

- `output_file_id` is parsed into `responses`.
- `error_file_id` is parsed into `errors`.
- `response_count`, `error_count`, and `has_errors` summarize the artifacts.
- `batch_status` preserves the provider's terminal state.
- `batch_succeeded` is true only when that state is `completed`.

The top-level `success` field reports whether artifact retrieval succeeded. A
failed, expired, or cancelled batch can therefore return `success: true` and
`batch_succeeded: false` when its diagnostic error file was retrieved correctly.
This distinction lets operators investigate provider failures without treating
the diagnostic download itself as another failed operation.

Every non-empty JSONL line must decode to a JSON object. Malformed or scalar
records raise a structured `GatewayError` containing the source file kind and
line number. Result and error artifacts remain in memory; no temporary files are
written.
