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
- Finish request-acquisition and retryable-status decisions before response
  handoff. Once body iteration starts, a transport or response-close failure
  closes the active response exactly once and must never reopen the file or
  duplicate records already yielded.
- Check the final provider-file HTTP status before consuming its body. Keep
  failure diagnostics body-free and free of credentials, URLs, identifiers,
  record data, and retained decoder exception payloads.
- Consume only `iter_chunked` byte streams and count `memoryview.nbytes`. Reject
  absent streams, non-byte chunks, empty zero-progress chunks, and chunks larger
  than the requested transport ceiling before package-owned buffering.
- Enforce total bytes, physical-line bytes, and the combined result-plus-error
  record count before excessive data is yielded.
- Validate and enforce `max_jsonl_physical_lines` as a batch-wide physical line
  ceiling shared across result and error files. Count blank and nonblank lines,
  including a final unterminated line, before decoding or parsing.
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
  post-handoff payload and close failure, no-replay, record-limit,
  byte-line-limit, batch-wide physical-line-limit, download-limit,
  compatibility, and error tests.

## Resumable checkpoint invariants

- Preserve all aggregate and non-checkpointed streaming APIs. Checkpointed
  delivery is opt-in through `iter_checkpointed_batch_records()` or
  `open_checkpointed_batch_records()`.
- Validate checkpoint structure and request identity without trimming,
  coercion, credential lookup, provider access, or database access.
- Treat the checkpoint schema version and digest framing as an authoritative
  compatibility contract. Incompatible framing requires a new version; never
  reinterpret an old digest under new rules.
- Hash a domain-separated, length-prefixed sequence that binds batch identity,
  endpoint alias, ordered file kind and file identifier, file-local line number,
  exact physical line bytes, and newline-termination state. Keep blank lines and
  CRLF framing significant and transport chunks insignificant.
- Revalidate from byte zero under existing byte, line, physical-line, record,
  timeout, retry-handoff, parser, and response-lifecycle limits. Do not yield
  records before exact checkpoint reproduction.
- Fail closed on prefix mutation, changed file identity, truncation at or before
  the checkpoint, inserted or removed prefix framing, or a different record at
  the checkpoint position. Keep diagnostics body-free and free of provider
  identifiers and checkpoint digests.
- Do not claim detection of mutation or truncation strictly after the
  acknowledged checkpoint. Successful prefix reproduction is not a whole-stream
  attestation; stronger suffix guarantees require a stable provider validator,
  authenticated digest, or separate full-stream manifest.
- Describe SHA-256 checkpoints only as deterministic change-detection evidence.
  They are not authentication, signatures, provider attestations, tenant
  credentials, or exactly-once delivery by themselves.
- Require the embedding host to protect checkpoint storage from tampering and
  rollback and to atomically coordinate checkpoint advancement with record
  effects or a proven idempotency boundary.
- Use the context-managed checkpoint API for early exits so all nested iterators
  and active responses close deterministically.
- Maintain 100% statement, branch, and public-docstring coverage across chunk
  independence, no-replay, file transitions, prefix mutation, truncation at or
  before the checkpoint, explicit unseen-suffix limitations, identity, framing,
  local validation, and cleanup behavior.

## Durable checkpoint-store invariants

- Keep `PostgresBatchResultCheckpointStore` optional and compatible with custom
  host-owned persistence implementations.
- Select tenant scope and consumer identity only at a trusted authenticated host
  boundary. Reject malformed names before database access.
- Persist the complete immutable checkpoint under a tenant-qualified compound
  key and reconstruct it through normal checkpoint validation on every load.
- Treat `expected_previous` as mandatory compare-and-swap evidence for every
  non-idempotent update. Never replace it with last-writer-wins behavior.
- Lock existing rows with `FOR UPDATE`. Close the missing-row race with
  `ON CONFLICT ... DO NOTHING` and locked reconciliation. Classify an unequal
  first writer as `initial_checkpoint_race`; do not leak raw database errors or
  checkpoint digests.
- Require both record and physical-line positions to increase on advancement.
  Exact repeats are idempotent; stale, forked, missing, and regressive updates
  fail without overwrite.
- `save_in_transaction` and `load_in_transaction` operate inside a caller-owned
  transaction and never commit or roll it back. Use them to coordinate local
  PostgreSQL record effects with checkpoint advancement.
- Do not describe this as a distributed exactly-once protocol. External side
  effects require an outbox, idempotency key, or separately reviewed recovery
  design.
- Keep forced RLS and `NOSUPERUSER NOBYPASSRLS` application-role requirements.
  Preserve byte-identical package/container migrations and fail-closed rollback
  while any acknowledgement evidence remains.
- Maintain deterministic concurrency, migration, rollback, live-PostgreSQL,
  documentation, and 100% production coverage tests.

## OpenTelemetry checkpoint signals

- Keep `OpenTelemetryCheckpointStore` optional, dependency-injected, and free of
  package-owned global OpenTelemetry configuration.
- Emit fixed operation, transaction-owner, and outcome labels only. Use a finite
  low-cardinality error vocabulary and disable automatic exception recording.
- Use `record_exception=False` and `set_status_on_exception=False` for every
  package-owned checkpoint span. On failure, explicitly set the host
  OpenTelemetry API's `StatusCode.ERROR` without a description when available;
  on success, leave status Unset.
- Never add tenant, consumer, batch, endpoint, file, digest, cursor, or DSN values
  to package-owned spans or metrics. Do not add exception messages, dynamic
  exception class names, provider payloads, or database errors either.
- The original checkpoint result or exact application exception is authoritative;
  tracer, metric, clock, optional status-code resolution, and status-mutation
  failures must not mask or replace application results or exceptions.
- Preserve package-owned versus caller-owned transaction labels without changing
  commit, rollback, compare-and-swap, or cursor ownership.
- Maintain 100% production statement, branch, and public-docstring coverage for
  success, conflict, validation, internal-error, duration, Error-status,
  Unset-status, confidentiality, delegation, and telemetry-failure paths.

## Checkpoint accepted-save audit invariants

- Keep `AuditedPostgresBatchResultCheckpointStore` optional and preserve the base
  durable store and custom host persistence contracts.
- Append one `checkpoint_save_accepted` event only after a save call succeeds,
  in the same PostgreSQL transaction as checkpoint persistence. Exact idempotent
  repeats are separate accepted-call events; validation/CAS failures create no
  success event.
- Use PostgreSQL `clock_timestamp()` for `recorded_at` so accepted-save event time
  reflects the insert itself, not transaction-start `NOW()`/`CURRENT_TIMESTAMP`
  in a long caller-owned transaction. Migration reapplication must reset that
  default idempotently without rewriting retained audit rows.
- Validate tenant, consumer, endpoint, batch, event, checkpoint, timestamp, and
  read limit without coercion. Keep reads tenant-qualified, newest-first, and
  bounded to at most 1,000 rows.
- Store only structured checkpoint audit fields. Do not add provider bodies,
  prompts, model output, credentials, DSNs, transport headers, exception text,
  or arbitrary free-form log content.
- Keep audit RLS enabled and forced. Application roles remain `NOSUPERUSER
  NOBYPASSRLS`. Reject ordinary UPDATE/DELETE through the row trigger and
  TRUNCATE through the statement trigger.
- Never call these controls cryptographic non-repudiation or administrator-proof
  tamper evidence. Owners, superusers, `BYPASSRLS`, disabled triggers, and
  physical database administration are outside this boundary.
- Keep package/container audit migration bytes identical, install them after the
  durable checkpoint schema on fresh data directories, and require explicit
  migration for existing PostgreSQL volumes.
- Rollback must refuse to erase non-empty audit evidence across tenant scopes.
  Retention, export, legal hold, disposal, and stronger immutable evidence are
  host/operator concerns.
- Maintain test-first transaction, event-time, validation, bounded-read,
  migration, rollback, trigger, compatibility, documentation, and 100%
  production statement/branch/public-docstring coverage.
