# Checkpoint audit export pagination assurance record

## Scope

This record documents the bounded keyset-pagination control used to traverse
`llm_result_checkpoint_audit_events` for export or reconciliation. It supplements
the append-only audit assurance record; it does not replace the database RLS,
mutation-rejection, rollback, or retention controls described there.

The commercial objective is practical and deliberately narrow: a host must be
able to move more than one bounded page of accepted-save audit evidence into a
separately governed retention system without inventing product-specific
pagination or materializing the entire audit history in memory.

## Threat and failure model

The implementation treats tenant scope, consumer name, endpoint alias, batch
identifier, page size, cursor, database row shape, row identity, and row ordering
as validation boundaries. Provider payloads and model output never select audit
scope or cursor state.

The bounded query uses the existing tenant-qualified checkpoint key and orders by
`checkpoint_audit_event_id DESC`. A continuation uses a strict primary-key
predicate:

```sql
AND checkpoint_audit_event_id < %s
ORDER BY checkpoint_audit_event_id DESC
LIMIT %s
```

The bound passed to SQL is exactly the validated public limit plus one. The extra
row is not returned to the caller; it only determines whether an older page
exists. A database adapter returning more than that bound is treated as an
internal integrity failure rather than silently expanding memory use.

Every materialized row is reconstructed through the strict
`CheckpointAuditEvent` validator and is then compared to the exact trusted
`(tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id)` key.
Rows must be strictly descending by audit identity. A cross-key row, duplicate
identity, ascending identity, malformed collection, malformed row, or cursor
outside signed PostgreSQL `BIGINT` range fails closed.

## Concurrency semantics

Keyset pagination intentionally avoids `OFFSET`. If page one ends at audit event
`800`, later committed events with larger identities cannot move the continuation
window because page two is anchored by `checkpoint_audit_event_id < 800`.
This prevents the common offset-shift duplicate/skip failure mode for newly
visible higher-key rows.

This is not equivalent to one database snapshot. PostgreSQL's default isolation
is `READ COMMITTED`, under which each statement sees rows committed before that
statement begins. A package-owned page call therefore may see database changes
that were not visible to the previous call. PostgreSQL documents that
`REPEATABLE READ` instead keeps all statements in one transaction on the snapshot
established by its first query. Hosts that require a single-snapshot export pass
must explicitly begin an appropriate caller-owned transaction before the first
page and repeatedly use `list_audit_event_page_in_transaction()` on that
transaction's cursor.

The package does not change caller transaction isolation automatically. Doing so
after the first query is prohibited by PostgreSQL, and doing so implicitly would
alter host-owned transaction semantics.

PostgreSQL identity values are navigation keys, not trusted wall-clock sequence
numbers. Gaps are valid, and allocation/commit ordering can differ across
concurrent transactions. A continuation cursor therefore proves only where the
next keyset query resumes. It does not prove that no later transaction can reveal
an event that was invisible to an earlier export pass.

## Security and privacy boundary

NIST SP 800-53 Rev. 5 AU-9 requires protection of audit information against
unauthorized access, modification, and deletion. NIST Release 5.2.0, issued on
August 27, 2025, remains the current minor release of Revision 5 and does not
remove this AU-9 protection boundary. The underlying audit table implements
tenant-qualified RLS and mutation rejection for ordinary application roles. This
pagination feature does not weaken those controls and does not add a write-capable
database permission.

NIST also describes stronger audit-protection enhancements such as write-once
media. This package does not claim that PostgreSQL alone provides administrator-
proof immutability. The bounded page API is the transport-neutral extraction
primitive by which an embedding host can copy evidence into a separately governed
immutable or write-once system under its own retention and access-control policy.
No destination, credential, exporter, background scheduler, object-store API, or
network client is introduced here.

Audit events continue to exclude prompts, provider bodies, model output,
credentials, DSNs, transport headers, and arbitrary exception text. Cursor values
are database identities, not secrets. Diagnostics remain fixed and body-free.

## Operational workflow

1. Select a trusted tenant, consumer, endpoint, and batch key after host
   authentication and authorization.
2. Choose a strict page limit from 1 through 1,000.
3. For ordinary incremental export, call `list_audit_event_page()` from
   `before_audit_event_id=None`, persist each page to the governed destination,
   and continue with `page.next_before_audit_event_id` until it is `None`.
4. If one PostgreSQL snapshot is required, begin a caller-owned `REPEATABLE READ`
   or stricter transaction before the first read and use the in-transaction page
   method for the entire pass.
5. Persist destination-side receipt, manifest, or cryptographic evidence when
   the retention requirement needs proof of delivery or completeness. The page
   cursor itself is not such proof.
6. Start a later reconciliation pass from the newest page to capture rows that
   became visible only after a previous non-snapshot export.

## Rollback

No database migration is introduced. Rolling back this feature removes only the
new public pagination API and documentation. The audit table and retained events
are unchanged. Existing `list_audit_events()` callers remain compatible.

Do not delete audit rows as a feature rollback. The existing rollback migration
continues to refuse removal of non-empty audit evidence.

## Verification contract

Permanent tests cover:

- strict `None` or positive signed-`BIGINT` cursor validation without coercion;
- immutable page tuples and a maximum of 1,000 returned events;
- strictly descending unique audit identities;
- a continuation cursor equal to the final returned identity;
- one-row bounded lookahead and a maximum SQL row request of 1,001;
- first-page and continuation SQL without `OFFSET`;
- strict `<` continuation semantics;
- trusted tenant/consumer/endpoint/batch revalidation on returned rows;
- fail-closed malformed collection, impossible driver overrun, and row-order
  behavior;
- package-owned reads that do not create an explicit package commit; and
- a live least-privilege PostgreSQL pass proving that a newer committed row
  between pages cannot drift into the older continuation window.

Final merge evidence is valid only after the full stacked dependency chain has
integrated and all required exact-head quality, security, coverage, packaging,
review, provenance, and release-acceptance gates have been regenerated against
the protected base.

## APA 7 references

Joint Task Force. (2020, updated 2025). *Security and privacy controls for
information systems and organizations* (NIST Special Publication 800-53,
Revision 5, Release 5.2.0). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

PostgreSQL Global Development Group. (2026). *SET TRANSACTION*. PostgreSQL 18
documentation. https://www.postgresql.org/docs/18/sql-set-transaction.html

PostgreSQL Global Development Group. (2026). *Concurrency control*. PostgreSQL
18 documentation. https://www.postgresql.org/docs/18/mvcc.html
