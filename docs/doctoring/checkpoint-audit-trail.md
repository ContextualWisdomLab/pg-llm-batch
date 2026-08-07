# Checkpoint audit trail assurance record

## Assurance objective

Provide a bounded, tenant-isolated, transaction-coupled audit trail for every
checkpoint value that the opt-in audited store successfully accepts. The trail
must support operator reconstruction without reclassifying telemetry as durable
audit evidence and without weakening the existing checkpoint compare-and-swap,
RLS, or transaction contracts.

## Threat model and exclusions

Protected against within the reviewed application deployment boundary:

- granting ordinary checkpoint workers audit UPDATE, DELETE, or TRUNCATE rights;
- overwriting or deleting retained accepted-save audit rows through ordinary SQL,
  with a separately scoped mutation-probe role exercising trigger rejection as
  defense-in-depth evidence;
- tenant-crossing reads or inserts when an ordinary `NOSUPERUSER NOBYPASSRLS`
  role uses the trusted package boundary;
- unbounded audit reads;
- silent loss of audit evidence after a checkpoint save succeeds;
- transaction-start timestamps misrepresented as the later accepted-save event
  time in long caller-owned transactions;
- destructive rollback while retained evidence exists; and
- fresh-container deployments that silently omit the audit schema.

Explicitly outside this assurance claim:

- PostgreSQL owners, superusers, `BYPASSRLS` roles, disabled triggers, storage
  administrators, or direct physical database tampering;
- cryptographic non-repudiation, signed events, immutable remote/WORM storage,
  or complete detection of administrator deletion;
- trusted database/server clock correctness or cryptographic time attestation;
- rejected save attempts, authentication failures, or a general-purpose
  security-event log;
- retention duration, legal hold, SIEM forwarding, and tenant identity mapping,
  all of which remain host/operator policy; and
- Docker entrypoint scripts as an upgrade mechanism for an existing data volume.

## Data minimization

The audit table retains only the trusted tenant/consumer key, endpoint and remote
batch identity, one fixed event action, validated checkpoint coordinates and
prefix digest, a database identity, and database timestamp. It excludes prompts,
provider result bodies, model output, credentials, DSNs, transport headers,
exception messages, and arbitrary free-form log text.

The `prefix_sha256` is deterministic checkpoint change-detection evidence. It is
not a signature or authentication tag and must not be represented as one.

## Transaction and event-time semantics

`AuditedPostgresBatchResultCheckpointStore.save_in_transaction()` delegates to
the existing compare-and-swap implementation and inserts the audit row only
after that call accepts the checkpoint. Both statements remain in the caller's
transaction. `save()` owns one connection and commits only after both operations
complete.

PostgreSQL documents `NOW()` and `CURRENT_TIMESTAMP` as the start time of the
current transaction. That value is stable during a transaction and therefore is
not an accurate accepted-save event time when a caller keeps a transaction open
before checkpoint persistence. `recorded_at` instead defaults to
`clock_timestamp()`, which PostgreSQL documents as the actual current time when
the function is called. The migration explicitly reapplies that default after
`CREATE TABLE IF NOT EXISTS` so rerunning the reviewed migration repairs earlier
development applications that used `NOW()` without mutating historical rows.

An idempotent repeated checkpoint creates another `checkpoint_save_accepted`
event. This is intentional: the row describes an accepted API action, not a
unique durable-state transition. A validation or compare-and-swap exception is
propagated unchanged and produces no success event.

An audit insertion failure is fail-closed for the surrounding save transaction.
The package does not catch it and then commit the checkpoint alone.

## Database immutability controls

`llm_result_checkpoint_audit_events` uses forced row-level security and a
single tenant policy based on transaction-local
`pg_llm_batch.tenant_scope`. `checkpoint_audit_row_immutability` rejects UPDATE
and DELETE per row. `checkpoint_audit_truncate_immutability` rejects TRUNCATE at
statement level; PostgreSQL documents TRUNCATE triggers as statement-only.

These triggers are application-level append-only controls, not administrator-
proof tamper detection. OWASP recommends stronger protection where audit
trustworthiness requires detection of modification/deletion; such deployments
should export or replicate events into separately governed immutable evidence.

## Migration and rollback

The package migration and Docker build-context migration are byte-identical. On
a new PostgreSQL data directory, the container orders durable checkpoint schema
before checkpoint audit schema. Existing data directories do not replay Docker
entrypoint initialization; operators apply
`apply_result_checkpoint_audit_schema()` or the exact reviewed SQL explicitly.
Reapplication is intentionally idempotent and resets the `recorded_at` default to
`clock_timestamp()` so a database that consumed an earlier development revision
of migration 0008 receives the corrected future-event timestamp semantics. It
does not rewrite retained audit records.

Rollback first removes FORCE RLS inside the same transaction so an owner-level
emptiness check can see rows for every tenant. If any audit row exists, rollback
raises SQLSTATE `55000`; the transaction restores FORCE RLS automatically. An
empty table may be dropped together with the trigger function.

## Live PostgreSQL verification boundary

CI contains a permanent read-only-code verification job backed by the exact
reviewed PostgreSQL 16 Bookworm image digest. The job creates one random isolated
temporary database and two random logins, each declared
`NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`.
Identifiers are composed with `psycopg.sql.Identifier`; generated passwords are
composed with `psycopg.sql.Literal` because PostgreSQL utility-statement grammar
does not accept a protocol bind parameter in `CREATE ROLE ... PASSWORD`.

The application role receives only `SELECT`, `INSERT`, and `UPDATE` on
`llm_result_stream_checkpoints`, `SELECT` and `INSERT` on
`llm_result_checkpoint_audit_events`, and `USAGE` plus `SELECT` on the exact
identity sequence returned by `pg_get_serial_sequence()` and safely decomposed
with `parse_ident()`. It receives no audit UPDATE, DELETE, or TRUNCATE right and
no blanket permission over other sequences in `public`.

A separate mutation-probe role receives only the audit-table rights needed to
exercise `SELECT`, `UPDATE`, `DELETE`, and `TRUNCATE` rejection. It receives no
checkpoint-table or audit-identity-sequence permission and is never used for
normal checkpoint persistence or audit reads. This separation proves both the
least-privilege application contract and the trigger defense-in-depth contract
without normalizing mutation authority for production workers.

The live test applies the durable checkpoint schema before the audit schema and
verifies that identical checkpoint keys in two tenant scopes remain
independently readable only through the application role's bound scope. An
unscoped application connection sees zero audit rows. Under a valid tenant
scope, the mutation-probe role's ordinary `UPDATE`, `DELETE`, and `TRUNCATE`
attempts must each fail with SQLSTATE `55000`. The owner-level rollback must also
fail with SQLSTATE `55000` while any tenant's audit evidence remains, after which
both tenants' retained events must still be readable through their authorized
application package scopes.

The same live test starts a caller-owned application transaction, observes the
transaction start, waits briefly, captures the wall clock immediately before an
audited save, and requires the retained event timestamp to fall between that
pre-save wall-clock observation and a post-save observation. This deterministically
rejects transaction-start `NOW()` semantics while preserving transaction
atomicity.

The test cleanup is bounded to the unique temporary database and two roles it
created. Independent creation flags guard partial setup, so a failure after either
role creation or before database creation does not silently leave a test login
behind. The CI token is `contents: read`; checkout uses
`persist-credentials: false`. The integration job has no repository write
permission and is not a branch-writing repair agent.

## Deterministic verification matrix

- Initial production RED: CI run `31138134741` on test-only head
  `3dfab0d6132e523396d2b2e27125aff34d8565e4` failed unit collection because
  `pg_llm_batch.checkpoint_audit` did not exist.
- Live-gate RED: CI run `31139284742` on head
  `467f40e7282b6916c7e681636550c7c215db88e2` failed the permanent workflow
  contract because the live PostgreSQL audit job did not yet exist.
- CI-integration refactor RED: after adding the live job, run `31139383985`
  exposed an older dependency-refresh test that hard-coded exactly two uv setup
  steps. The contract was generalized to require every setup-uv occurrence to
  use the same immutable reviewed pin and explicit cache pruning, independent of
  job count.
- Live setup RED: exact-head run `31139440808` reached the pinned PostgreSQL
  service and all ordinary unit/quality/container jobs passed, but the live test
  correctly exposed invalid use of a protocol bind parameter in PostgreSQL
  `CREATE ROLE ... PASSWORD`. The setup was changed to psycopg's composable
  identifier/literal API and partial-provision cleanup was made fail-safe before
  re-verification.
- Least-privilege RED: exact-head run `31148349909` on
  `5dfdecfaf1fb7a4d88be338bd44eddb69814a174` failed the permanent role-binding
  contract because one application role still held audit mutation rights and a
  blanket public-schema sequence grant. The repaired integration separates a
  normal application role from a bounded mutation-probe role and resolves only
  the exact audit identity sequence.
- Event-time RED: test-only heads `9e43420097faabd97deab079c34c5e4e0207eb86`,
  `19b39a23dc7e29a467cc6c0d6817f06b5da1e880`, and
  `78184f6202d06831800ef3e90db498e9e04e26b5` require wall-clock insert-time
  semantics, a realistic long caller-owned transaction, and idempotent repair of
  the old transaction-start default before the migration implementation.
- Public model: immutable accepted-save event; invalid identifiers, action,
  checkpoint fields, event identity, and timestamp fail closed.
- Read bound: integers 1 through 1,000 only; booleans and coercible values are
  rejected.
- Transaction coupling: owned saves commit once after checkpoint and audit;
  caller-owned saves do not commit.
- Event time: `clock_timestamp()` is evaluated at accepted-save row insertion;
  transaction-start `NOW()`/`CURRENT_TIMESTAMP` is prohibited for `recorded_at`.
- Failure semantics: a rejected delegated save creates no success event.
- Query semantics: tenant-qualified exact checkpoint key, newest-first order,
  parameterized `LIMIT`, and malformed database row/collection rejection.
- Least privilege: application and mutation-probe roles are separate, application
  audit rights are `SELECT`/`INSERT` only, sequence rights target only the exact
  audit identity sequence, and mutation checks cannot borrow production rights.
- Workflow contracts: PostgreSQL service, DSN, credential-free checkout, live
  command, and every setup-uv version/cache control are asserted inside their
  exact job or step rather than through repository-wide string counts.
- Migration: forced RLS, fixed action CHECK, descriptive snake_case objects,
  event-time default repair, UPDATE/DELETE and TRUNCATE rejection,
  package/container byte identity, and ordered image installation.
- Rollback: non-empty evidence blocks destructive rollback across tenants.
- Quality target: 100% production statement, branch, and public-docstring
  coverage plus exact-head CI, live PostgreSQL integration, release acceptance,
  security, supply-chain, and independent review before merge.

## Standards mapping

NIST SP 800-53 Rev. 5 AU-3 motivates retaining enough structured information to
reconstruct what happened, when, where, source, and outcome. This slice supplies
those fields at the package's checkpoint-storage boundary: fixed action, database
event time, package/database location, tenant/consumer source identity, and
successful acceptance outcome.

OWASP's Logging Cheat Sheet distinguishes application audit trails from generic
infrastructure logs, recommends recording business/security-relevant actions,
minimizing sensitive content, restricting log access, and protecting retained
logs from modification/deletion. This design therefore keeps audit evidence in a
separate table, omits payload/secrets, applies tenant RLS, and rejects ordinary
row mutation while explicitly documenting the stronger administrator-tamper
controls it does not provide.

PostgreSQL 18 `CREATE TRIGGER` defines TRUNCATE as a supported trigger event and
states that TRUNCATE triggers are statement-level. The migration uses a separate
statement trigger rather than pretending a row trigger can intercept TRUNCATE.

PostgreSQL 18 date/time documentation distinguishes transaction time from actual
current time: `CURRENT_TIMESTAMP`/`NOW()` are fixed at transaction start, while
`clock_timestamp()` changes with the actual clock even within a statement. Audit
`recorded_at` therefore uses `clock_timestamp()` because this record represents
when the accepted-save insert occurred, not when an enclosing caller transaction
began.

## APA 7 references

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53, Revision 5). https://doi.org/10.6028/NIST.SP.800-53r5

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series.
https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

PostgreSQL Global Development Group. (2026). *CREATE TRIGGER* (PostgreSQL 18
documentation). https://www.postgresql.org/docs/18/sql-createtrigger.html

PostgreSQL Global Development Group. (2026). *Date/time functions and operators*
(PostgreSQL 18 documentation).
https://www.postgresql.org/docs/18/functions-datetime.html
