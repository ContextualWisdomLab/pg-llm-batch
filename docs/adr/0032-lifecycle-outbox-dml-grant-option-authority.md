# ADR 0032: Lifecycle Outbox DML Grant-Option Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox application role is intentionally limited to tenant-qualified `SELECT` and `INSERT`. ADR 0031 already rejects owner authority, `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` across the effective/session-selectable/administerable role closure.

A fresh authority review found a separate capability hidden inside otherwise-allowed DML: PostgreSQL `WITH GRANT OPTION`. A principal holding `SELECT` or `INSERT` with grant option can grant that object privilege onward to another role. That delegation authority is not required to enqueue or read lifecycle evidence and widens the database authorization graph outside the package-owned runtime boundary.

This is not described as an automatic RLS bypass. A delegated ordinary role remains subject to PostgreSQL row-security rules. The risk is authority delegation itself: the application identity can manufacture new readers or writers, including grants to roles whose wider database attributes are managed outside the package. The canonical runtime contract therefore distinguishes *using* `SELECT`/`INSERT` from *delegating* them.

PostgreSQL exposes grant-option state through the access-privilege inquiry functions. `WITH GRANT OPTION` can be appended to the privilege checked by `has_table_privilege`, `has_any_column_privilege`, and related functions. `has_any_column_privilege` also covers whole-table privileges and column-level grants, which lets runtime admission fail closed for either form without parsing ACL text.

## Decision

`_require_rls_application_role()` rejects any role in the existing effective/session-selectable/administerable closure that has either:

- `SELECT WITH GRANT OPTION` on any outbox column or the whole table; or
- `INSERT WITH GRANT OPTION` on any outbox column or the whole table.

The check uses schema-qualified `pg_catalog.has_any_column_privilege` against the already-resolved canonical outbox relation. Ordinary non-grantable `SELECT` and `INSERT` remain the supported application DML contract.

The package does not silently revoke grant options. Operator/migration authority remains responsible for ACL repair. Runtime admission only proves that the live connection authority is still inside the package boundary before tenant binding or outbox data SQL.

## Alternatives considered

### Permit grant options because RLS still applies

Rejected. RLS controls row visibility and mutation for a principal; it does not make authorization delegation part of the application domain. The runtime has no product need to grant outbox privileges to other principals.

### Check only table-level grant options

Rejected. PostgreSQL permits column-level `SELECT` and `INSERT` grants. `has_any_column_privilege` covers both table and column forms and therefore avoids a silent delegation gap.

### Parse `relacl` and `attacl` directly

Rejected. PostgreSQL already provides access-privilege inquiry functions that account for effective privileges and grant options. Reimplementing ACL parsing would be more brittle and easier to diverge from PostgreSQL semantics.

### Revoke grant options automatically at runtime

Rejected. Runtime code does not own database authorization policy. Silent ACL mutation would cross the application/operator bounded-context boundary and could invalidate independently managed access-control evidence.

## Verification lineage

- static RED `c9dd5189488d6f5acfdfe1d5919e88dd593c3398` requires both grant-option predicates in the live role-authority query;
- PostgreSQL RED specimen `4f890a3da639bea9ef7444265dcc670d9a914791` creates an otherwise-minimal runtime login with outbox `SELECT, INSERT WITH GRANT OPTION` and requires package admission to fail closed;
- executable refinement `e50674cc534ea402b99f38f4c3319bddb93e2d52` gives the delegated role explicit schema usage, grants `SELECT` from the runtime identity, and requires the recipient to execute a real outbox read, proving usable delegation rather than catalog metadata alone;
- CI wiring `8a51ec8a96e1e47f659fc7235f5d118686d5a1c9` places that specimen in the PostgreSQL/container acceptance lane;
- causal production repair `146e521a439c038e0b418a7c93c114140ad7fc1f` rejects table- or column-level `SELECT`/`INSERT` grant options anywhere in the existing role closure.

Exact-head hosted GREEN is required before this ADR can become Accepted. The executable specimen is evidence design until the exact repaired head actually runs in the hosted PostgreSQL lane.

## Consequences

The runtime identity may use only the DML it needs and may not redistribute that DML authority. Security review and SOC 2/CSAP evidence can therefore treat outbox privilege delegation as operator-owned authorization change rather than application behavior. The added checks remain in the existing single catalog round trip and do not add a second database query.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 5.8. Privileges*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 9.27. System information functions and operators*. https://www.postgresql.org/docs/18/functions-info.html
