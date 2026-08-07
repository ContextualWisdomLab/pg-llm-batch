# ADR 0010: Bounded checkpoint-audit export pagination

- **Status:** Accepted for the stacked implementation
- **Date:** 2026-08-07
- **Decision owners:** ContextualWisdomLab
- **Depends on:** ADR 0009 and the append-only checkpoint audit trail

## Context

The package-owned audit store previously exposed only one newest-first bounded
read. That is appropriate for an operator console, but not sufficient for a
host that must move a longer retained audit history to separately governed
storage. Leaving multi-page traversal to every embedding product would produce
incompatible cursor semantics and would encourage `OFFSET` pagination, which can
skip or duplicate rows when the visible set changes between requests.

The existing audit identity is a PostgreSQL `BIGINT GENERATED ALWAYS AS
IDENTITY` primary key. The compound checkpoint-key index already ends in
`checkpoint_audit_event_id DESC`, so the table can support bounded keyset
pagination without a schema migration or a second ordering column.

## Decision

Add an opt-in `CheckpointAuditPage` contract and two audit-store methods:

- `list_audit_event_page()` for package-owned page reads; and
- `list_audit_event_page_in_transaction()` for hosts that own the surrounding
  PostgreSQL transaction.

Each request validates a strict 1..1,000 page size and an optional positive
signed-`BIGINT` `before_audit_event_id`. The first page orders by
`checkpoint_audit_event_id DESC`. Continuations add the strict predicate
`checkpoint_audit_event_id < before_audit_event_id` and preserve the same order.
The SQL query requests only `limit + 1` rows. At most `limit` rows are returned;
the lookahead row only proves that an older continuation exists. When a
continuation exists, `next_before_audit_event_id` is exactly the identity of the
last returned event.

Every returned row is revalidated as a `CheckpointAuditEvent`, rechecked against
the trusted tenant/consumer/endpoint/batch key, and required to be strictly
descending. A database adapter that returns a non-sequence or more than the
bounded query size fails closed.

## Concurrency boundary

Keyset traversal solves offset drift, not snapshot isolation. Rows committed
after page one with identities greater than the cursor cannot move or duplicate
older rows already traversed. However, package-owned calls execute as separate
transactions and therefore do not promise one historic database snapshot.

A host that requires one snapshot for an export pass must own a PostgreSQL
`REPEATABLE READ` or stricter transaction and call the in-transaction method on
one cursor. The package does not silently alter transaction isolation because
that would change caller-owned database semantics.

Identity allocation order is not a cryptographic chronology and may contain
gaps. A transaction can allocate an identity before another transaction and
commit later. The cursor is therefore a database navigation key, not a statement
that all real-world events before or after a wall-clock instant have been
captured.

## Security and acquisition boundary

The page remains tenant-qualified and inherits forced RLS and ordinary-role
append-only controls from ADR 0009. It does not create a new database object,
credential, network destination, export worker, background process, or write
permission. It never accepts provider or model output as tenant or consumer
identity.

The feature is intended to make bounded export to separately governed immutable
or write-once retention storage practical. It does not itself provide immutable
external storage, cryptographic non-repudiation, signed completeness evidence,
administrator-proof tamper detection, or delivery acknowledgement. Those remain
host/operator controls. A later cryptographically protected export manifest can
be layered on this stable pagination contract without changing database
navigation semantics.

## Alternatives rejected

### SQL OFFSET/LIMIT

Rejected because additions or visibility changes before an offset can shift the
subsequent window, producing duplicates or omissions during a long-running
export.

### Unbounded iterator or fetch-all export

Rejected because acquisition-grade audit volume is not bounded by a single
operator interaction. Materializing arbitrary retained history would weaken the
package's existing memory-safety policy.

### Implicit REPEATABLE READ in the package-owned API

Rejected because changing isolation belongs to the owner of the transaction and
must occur before the first transaction query. The in-transaction API gives a
host an explicit way to obtain one snapshot without the package surprising
other database work.

### Timestamp cursor

Rejected because timestamps are not unique and database wall-clock values are
not a total order. The existing primary-key identity is already indexed and
provides an unambiguous strict continuation boundary.

## Verification

Permanent deterministic tests require strict cursor validation, immutable page
shape, strictly descending identities, one-row lookahead, no `OFFSET`, exact
`<` keyset continuation, trusted-key row revalidation, bounded driver output,
and no package commit during owned page reads. Integration/release gates remain
required after this stack is reconciled onto protected `main`.

## Consequences

Operators gain a package-owned bounded traversal primitive suitable for durable
audit export and acquisition diligence. Existing `list_audit_events()` behavior
is unchanged. No migration, release version, or publication authority is added.

The operational tradeoff is explicit: callers choosing independent page calls
accept normal transaction-to-transaction visibility changes; callers requiring a
single snapshot must own and configure that transaction deliberately.
