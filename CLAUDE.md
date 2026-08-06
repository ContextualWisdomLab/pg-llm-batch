# CLAUDE.md

## Tenant lifecycle invariants

- Preserve the standalone client, its four-argument recorder seam, and the
  explicit `standalone` database scope.
- Never derive tenant scope from provider metadata, remote identifiers, request
  bodies, model output, endpoint aliases, or transport headers.
- Validate tenant scope before observation reservation, credential lookup,
  provider I/O, or database I/O.
- Bind validated scope as a parameter with transaction-local `set_config`
  before lifecycle table access.
- Include tenant scope in every lifecycle lookup, unique identity, conflict
  target, and operational status index.
- Treat the custom setting as a trusted application boundary rather than a
  credential. A database role with arbitrary SQL can call `set_config` for an
  arbitrary tenant scope, so generic tenant-controlled SQL, SQL injection, and
  incorrect identity mapping remain outside the RLS guarantee.
- Keep row-level security enabled and forced. Production application roles are
  `NOSUPERUSER NOBYPASSRLS`.
- Keep owner-enforcement relaxation, legacy backfill, constraint migration, and
  forced-RLS restoration inside one atomic PostgreSQL statement.
- Keep `pg_llm_batch/schema.sql` and
  `docker/postgres/init/02_schema.sql` byte-for-byte identical.
- Keep README, operator, architecture, ADR, doctoring, and CHANGELOG contracts
  synchronized with every tenant security or migration change.
- Maintain 100% production statement, branch, and public-docstring coverage.
  Add realistic migration, rollback, compatibility, security, and
  tenant-isolation tests before implementation changes.

## Release evidence invariants

- Never validate release artifacts by checking a pathname and reopening that
  pathname later. Hold the release-directory descriptor for enumeration,
  artifact open, hashing, and final membership validation.
- Traverse absolute paths from `/` and relative paths from `.` with
  descriptor-relative `O_DIRECTORY | O_NOFOLLOW`; reject parent traversal and
  every symlinked or non-directory component.
- Open artifact names with descriptor-relative `O_NOFOLLOW | O_NONBLOCK`, require
  a regular file from `fstat`, stream bytes through bounded `os.read`, and reject
  size, device, inode, type, modification-time, or change-time drift.
- Compare the initial and final bounded directory-name sets from the same open
  directory. Do not expose arbitrary operating-system exceptions or unbounded
  names in diagnostics.
- Fail closed when the runtime lacks required descriptor or no-follow
  capabilities. Do not add a pathname fallback for portability.
- Preserve the separation between reproducibility evidence and publication,
  signing, attestation, release approval, or artifact reuse authority.
- Maintain test-first concurrency, unsupported-platform, bounded-enumeration,
  identity, documentation, and rollback contracts with 100% production
  statement, branch, and public-docstring coverage.

## Provider result streaming invariants

- Preserve the aggregate `BatchAPIClient.download_results()` contract; use the
  opt-in `StreamingBatchAPIClient` for incremental output.
- Inherit and preserve credential lookup, HTTPS URL validation, disabled
  redirects, bounded idempotent GET retry, timeouts, provider identifier
  validation, and decoded-byte limits.
- Check the final provider-file HTTP status before consuming its body. Keep
  failure diagnostics body-free and free of credentials, URLs, identifiers,
  record data, and retained decoder exception payloads.
- Consume only `iter_chunked` byte streams and count `memoryview.nbytes`. Reject
  absent streams, non-byte chunks, empty zero-progress chunks, and chunks larger
  than the requested transport ceiling before package-owned buffering.
- Enforce total bytes, physical-line bytes, and the combined result-plus-error
  record count before excessive data is yielded.
- Decode each nonblank physical line as strict UTF-8 and require one unambiguous
  JSON object. Preserve output-before-error order, CRLF handling, and final
  records without a terminating newline; reject non-finite numbers and duplicate
  object names.
- Translate decoder failures after leaving the active provider exception handler
  so exported `GatewayError` objects have no cause or context retaining provider
  bytes or text.
- Use `open_batch_records()` when a consumer may stop early. It owns and closes
  the public iterator, each nested file iterator, and the active HTTP response.
  Never rely on a bare `async for` break to call `aclose()` automatically.
- Keep library-owned memory bounded to one line and one decoded record. Treat
  downstream collection, persistence, transformation, lifecycle ownership, and
  backpressure as host responsibilities.
- Maintain 100% production statement, branch, and public-docstring coverage with
  deterministic split-chunk, invalid-stream, zero-progress, invalid-encoding,
  malformed-JSON, exception-sanitization, early-close, nested-close,
  record-limit, line-limit, download-limit, compatibility, and error tests.
