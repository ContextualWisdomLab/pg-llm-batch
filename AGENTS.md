# AGENTS.md

## Code-owner review gates — disabled (on hold)

As of 2026-08-04, code-owner review requirements
(`require_code_owner_reviews` in branch protection and
`require_code_owner_review` in rulesets) are disabled across the
ContextualWisdomLab organization. There is currently one maintainer, so a
code-owner approval gate cannot be satisfied. Do not re-enable these settings or
add CODEOWNERS-based merge gates until multiple independent maintainers exist.

## Tenant lifecycle security contract

- Preserve standalone operation under the exact `standalone` tenant scope and
  keep the existing four-argument lifecycle-recorder interface source
  compatible.
- Derive `tenant_scope` only from an authenticated and authorized host boundary.
  Provider metadata, remote identifiers, request payloads, model output,
  transport headers, and endpoint aliases are never tenant authorities.
- Validate tenant context before observation reservation, credential
  resolution, provider I/O, or database I/O.
- Bind tenant context with parameterized, transaction-local `set_config`; every
  lifecycle lookup, conflict target, and operational index must be
  tenant-qualified.
- Treat the custom PostgreSQL setting as a trusted application boundary, not a
  credential. A role with arbitrary SQL can select an arbitrary tenant scope;
  do not expose the lifecycle application role through generic tenant-controlled
  SQL, and never describe RLS as a substitute for authorization or
  SQL-injection prevention.
- Keep PostgreSQL row-level security enabled and forced. Application roles must
  be `NOSUPERUSER NOBYPASSRLS`; administrative bypass identities are outside
  the application isolation guarantee.
- Migrations must restore forced RLS within the same atomic SQL statement that
  relaxes owner enforcement, preserve legacy rows under `standalone`, remain
  idempotent, and keep the packaged and Docker initialization schemas
  byte-for-byte identical.
- Update the README, operator guide, architecture, ADR, doctoring, and CHANGELOG
  whenever tenant identity, role, migration, direct-SQL, or rollback contracts
  change.
- Maintain 100% production statement, branch, and public-docstring coverage with
  realistic tenant-isolation, migration, rollback, compatibility, and
  concurrency tests.

## Reproducible release evidence security contract

- Treat release build directories and artifact names as untrusted concurrent
  filesystem inputs. Do not reintroduce pathname check-then-open verification.
- Require descriptor-relative `os.open`, descriptor-based `os.scandir`,
  `O_DIRECTORY`, `O_NOFOLLOW`, and `O_NONBLOCK`; unsupported runtimes fail
  closed before reading an artifact.
- Walk every release-directory component from an opened root or current
  directory without following symlinks. Reject `..` traversal.
- Open wheel and source-distribution entries relative to the held release
  directory descriptor. Hash with bounded `os.read`, derive size from the same
  open file description, and compare inode metadata before and after reading.
- Re-scan the same held directory descriptor after both reads and reject changed
  membership. Keep missing or extra count diagnostics filesystem-order
  independent and bounded to at most three enumerated names.
- Keep the release verifier and descriptor-relative manifest writer read-only
  with respect to release authority. They do not publish, attest, sign, approve,
  or authorize reuse of pull-request artifacts.
- Update architecture, ADR, doctoring, CHANGELOG, and deterministic security
  tests whenever artifact identity, path traversal, concurrency, portability,
  or rollback semantics change.

## Provider result streaming contract

- Keep `BatchAPIClient.download_results()` source compatible and make incremental
  retrieval an explicit opt-in through `StreamingBatchAPIClient`.
- Preserve inherited credentials, HTTPS validation, disabled redirects, bounded
  idempotent GET retries, request timeouts, identifier validation, and total
  decoded-byte limits.
- End retry eligibility before response handoff. After body iteration begins, a
  transport or response-close failure must close the active response exactly
  once, raise bounded body-free diagnostics, and never reopen the file or replay
  records already yielded to the caller.
- Reject non-success provider-file responses before body consumption. Never put
  provider bodies, record contents, URLs, credentials, or identifiers into
  diagnostics, telemetry, or retained exception cause/context links.
- Consume only non-empty bounded byte chunks; reject missing streams, non-byte
  chunks, zero-progress chunks, and chunks larger than the requested transport
  ceiling before package-owned line buffering.
- Enforce total bytes, one physical JSONL line, and the combined
  output-plus-error record count before yielding excessive data.
- Enforce `max_jsonl_physical_lines` as one batch-wide physical line budget
  shared by result and error files. Count every newline-terminated or final
  unterminated line, including blank lines, before UTF-8 or JSON parsing.
- Decode each nonblank line as strict UTF-8 and require one unambiguous JSON
  object. Preserve deterministic output-then-error ordering, CRLF support, and
  final lines without a newline; reject non-finite numbers and duplicate names.
- Raise sanitized decoder failures only after leaving the active provider
  exception handler so exported errors do not retain provider bytes or text.
- Make lifecycle ownership explicit. `open_batch_records()` is the supported
  boundary for consumers that may stop early; it closes the outer iterator,
  nested file iterator, and active HTTP response. Never claim that a bare
  `async for` break automatically calls `aclose()`.
- Keep library buffering bounded to one line and one decoded record. Document
  that downstream consumers own backpressure and can recreate aggregate memory
  use by collecting every record.
- Maintain 100% production statement, branch, and public-docstring coverage with
  deterministic split-chunk, malformed-input, byte-limit, record-limit,
  physical-line-limit, compatibility, cleanup, cancellation, post-handoff
  transport, no-replay, and body-free error tests.
- Update README, architecture, ADR, operator documentation, doctoring, and
  CHANGELOG whenever streaming resource, ordering, lifecycle, validation, or
  compatibility contracts change.
