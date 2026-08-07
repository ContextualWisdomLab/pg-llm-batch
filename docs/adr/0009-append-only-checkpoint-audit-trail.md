# ADR 0009: Append-only checkpoint accepted-save audit trail

- **Status:** Proposed
- **Date:** 2026-08-07
- **Decision owners:** ContextualWisdomLab maintainers

## Context

The durable checkpoint store can make local PostgreSQL record effects and
checkpoint advancement atomic, and the OpenTelemetry wrapper can expose
low-cardinality operational signals. Neither is durable application audit
evidence. Telemetry may be sampled, dropped, expired, or exported outside the
checkpoint transaction, while the checkpoint table is a mutable current-state
projection.

Acquisition and regulated-enterprise due diligence commonly asks whether a
business-relevant state change can be reconstructed after the fact without
relying on transient observability. NIST SP 800-53 Rev. 5 AU-3 requires audit
records to establish what occurred, when it occurred, where it occurred, the
source, and the outcome. OWASP likewise distinguishes application audit trails
from ordinary infrastructure logs and recommends protecting retained events
against unauthorized modification or deletion.

## Decision

Add an opt-in `AuditedPostgresBatchResultCheckpointStore` backed by
`llm_result_checkpoint_audit_events`.

Every **successful checkpoint save call** appends one
`checkpoint_save_accepted` row inside the same PostgreSQL transaction as the
checkpoint save. An exact idempotent repeat therefore creates another audit row:
the event records an accepted application action, not a claim that a distinct
checkpoint state transition occurred. A rejected validation or compare-and-swap
operation creates no success row.

Each event records the trusted tenant and consumer identity, the exact endpoint
and remote batch key, the complete validated checkpoint coordinates and prefix
digest, a fixed action vocabulary, a database-generated monotonic identity, and
a database timestamp. It deliberately excludes provider payloads, prompts,
model output, credentials, DSNs, transport headers, and exception text.

Audit reads are tenant-qualified, newest-first, and bounded to at most 1,000
rows per call. The package exposes caller-owned and package-owned transaction
forms so hosts can compose audit reads with their own PostgreSQL transaction
boundary.

The table uses forced row-level security with the same trusted
`pg_llm_batch.tenant_scope` boundary as checkpoint persistence. `UPDATE` and
`DELETE` are rejected by a row trigger; `TRUNCATE` is rejected by a statement
trigger because PostgreSQL supports TRUNCATE triggers only at statement level.
The rollback script temporarily relaxes FORCE RLS inside its transaction solely
so an owner-level emptiness check can observe every tenant; it refuses to drop a
non-empty audit table.

Package and Docker initialization migrations remain byte-identical. The bundled
PostgreSQL image installs the audit migration after the durable checkpoint
schema on **fresh data directories only**. Existing PostgreSQL volumes must run
`apply_result_checkpoint_audit_schema()` or the reviewed migration explicitly;
Docker entrypoint initialization is not an upgrade mechanism.

## Security and assurance boundary

This design is append-only for ordinary application roles through the reviewed
package/database contract. It is **not** cryptographic non-repudiation or
administrator-proof tamper evidence. A PostgreSQL owner, superuser, role with
`BYPASSRLS`, or administrator able to disable triggers or rewrite storage is
outside the guarantee. Stronger requirements need separately governed WAL or
logical-decoding retention, remote write-once storage, signed/hash-chained audit
records, or another independently protected evidence system.

The fixed event action and table constraints are defense in depth, not tenant
authorization. Hosts still derive tenant and consumer identity only after their
own authentication and authorization boundary and must not expose arbitrary SQL
to tenant-controlled callers.

## Consequences

- Enterprise operators gain durable, transaction-coupled reconstruction of
  successful checkpoint acceptance.
- Accepted idempotent retries are visible rather than silently collapsed.
- Audit retention consumes database storage and therefore requires explicit
  capacity, retention, export, and disposal policy at the host layer.
- A failed audit insert causes the surrounding checkpoint transaction to fail
  rather than silently accepting state without required audit evidence.
- The base checkpoint store remains available for deployments that do not choose
  this stronger audit contract.

## Verification

Deterministic tests require strict bounded read limits, immutable public event
values, tenant-qualified SQL, transaction coupling, no success event after a
rejected save, forced RLS, row and TRUNCATE mutation rejection, byte-identical
package/container migrations, ordered fresh-image installation, and fail-closed
non-empty rollback. Production statement, branch, and public-docstring coverage
remain 100%.

## References

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53, Revision 5). https://doi.org/10.6028/NIST.SP.800-53r5

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series.
https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

PostgreSQL Global Development Group. (2026). *CREATE TRIGGER* (PostgreSQL 18
documentation). https://www.postgresql.org/docs/18/sql-createtrigger.html
