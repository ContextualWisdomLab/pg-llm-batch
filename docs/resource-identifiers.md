# Provider resource identifier policy

Batch and file identifiers cross an authenticated URL-path boundary. The client
therefore validates them before resolving credentials or issuing a request.

Accepted identifiers:

- contain 1–256 ASCII characters;
- begin with a letter or digit; and
- use only letters, digits, `.`, `_`, `:`, or `-` thereafter.

This covers conventional OpenAI-compatible identifiers, deployment-qualified
identifiers, and UUIDs while excluding path separators, traversal segments,
queries, fragments, percent escapes, controls, whitespace, and Unicode lookalike
characters.

The same policy applies to:

- `memory://<file_id>` payload references;
- uploaded `input_file_id` values;
- caller-supplied batch IDs used for polling or cancellation; and
- provider-supplied output and error file IDs used for follow-up downloads.

Validation occurs before the next credential lookup. A malformed caller ID never
loads an API key, and a compromised status response cannot steer a second
authenticated request to an unintended path.
