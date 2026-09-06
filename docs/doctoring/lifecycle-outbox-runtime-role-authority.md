# Lifecycle outbox runtime role authority

The lifecycle outbox application identity is a tenant-scoped append-only DML identity, not a database-maintenance identity. Runtime admission follows PostgreSQL effective `CURRENT_USER`; DSN text and login identity are not authorization evidence after `SET ROLE`.

Before the package binds `pg_llm_batch.tenant_scope` or executes outbox data SQL, the live role/relation query must prove all of the following at the same admission point:

- `CURRENT_USER` is neither `SUPERUSER` nor `BYPASSRLS`;
- `public.llm_context_lifecycle_outbox` still has both `relrowsecurity` and `relforcerowsecurity` enabled;
- `CURRENT_USER` is not the table owner and cannot exercise, select, or administer the owner role through `USAGE`, `SET`, or `MEMBER WITH ADMIN OPTION`;
- the role has no `TRUNCATE`, `DELETE`, or table/column `UPDATE` privilege on the outbox;
- the role has no table-level or column-level `REFERENCES` privilege on the outbox; and
- the role has no `TRIGGER` privilege on the outbox.

Inert owner-role membership granted with `INHERIT FALSE, SET FALSE` and without admin option is not rejected merely because the membership edge exists. PostgreSQL 16+ distinguishes membership from immediately inherited privileges and `SET ROLE` authority.

`TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` are separated from the application identity for different reasons. `TRUNCATE` is a whole-table destructive operation outside ordinary row-security filtering. `DELETE` and `UPDATE` remain RLS-filtered, but that does not make them compatible with append-only durable publication intent: a tenant can erase or rewrite its own committed replay evidence. `REFERENCES` can be granted at column level and creates external dependency authority. `TRIGGER` permits executable behavior to be attached to the relation.

The prior runtime path retained `UPDATE` only because replay preflight used `SELECT ... FOR UPDATE`. PostgreSQL requires `UPDATE` privilege for a locking `SELECT`; that coupling made the least-privilege contract internally inconsistent because the intended runtime role otherwise needs only `SELECT` and `INSERT`. Replay serialization now uses `pg_catalog.pg_advisory_xact_lock(bigint)` on a deterministic tenant/event coordination key, followed by a plain tenant-qualified `SELECT`. Transaction-scoped advisory locking preserves same-identity package serialization without granting ambient row mutation.

The advisory key is a signed 64-bit projection of SHA-256 over the validated tenant scope, a NUL separator, and evidence ID. It is coordination metadata only. Durable identity remains the full `(tenant_scope, evidence_id)` UNIQUE key plus exact row revalidation. A coordination-key collision can delay unrelated work but cannot merge durable identities or authorize a different row.

## Deployment guidance

Use a distinct operator/migration role for schema ownership, grants, triggers, constraints, indexes, migrations, recovery reconciliation, and any explicit lifecycle-retention or deletion process. The runtime application role should receive the package's required `SELECT` and `INSERT` privileges and must not receive `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER`, directly or through an exercisable inherited role.

A representative audit query is:

```sql
SELECT
    current_user,
    r.rolsuper,
    r.rolbypassrls,
    c.relrowsecurity,
    c.relforcerowsecurity,
    r.oid = c.relowner AS is_owner,
    pg_catalog.pg_has_role(current_user, c.relowner, 'USAGE') AS owner_usage,
    pg_catalog.pg_has_role(current_user, c.relowner, 'SET') AS owner_set,
    pg_catalog.pg_has_role(
        current_user,
        c.relowner,
        'MEMBER WITH ADMIN OPTION'
    ) AS owner_admin,
    pg_catalog.has_table_privilege(current_user, c.oid, 'TRUNCATE') AS can_truncate,
    pg_catalog.has_table_privilege(current_user, c.oid, 'DELETE') AS can_delete,
    pg_catalog.has_any_column_privilege(current_user, c.oid, 'UPDATE') AS can_update,
    pg_catalog.has_any_column_privilege(current_user, c.oid, 'REFERENCES') AS can_reference,
    pg_catalog.has_table_privilege(current_user, c.oid, 'TRIGGER') AS can_trigger
FROM pg_catalog.pg_roles AS r
JOIN pg_catalog.pg_class AS c
  ON c.oid = pg_catalog.to_regclass('public.llm_context_lifecycle_outbox')
WHERE r.rolname = current_user;
```

For an admitted application identity, the two RLS flags are `true` and every authority/bypass boolean is `false`.

Do not repair a failing runtime identity by weakening forced RLS, granting `UPDATE` for `FOR UPDATE`, or suppressing the package guard. Revoke or separate the conflicting authority and use the advisory-lock path already implemented by the package.

## Executable acceptance

`tests/smoke_context_lifecycle_outbox_effective_role_authority.sh` is the real PostgreSQL acceptance surface. It must prove ordinary tenant visibility, inert owner-membership compatibility, raw `BYPASSRLS` visibility, owner ability to alter forced-owner enforcement, RLS-exempt `TRUNCATE`, tenant-local `DELETE`, tenant-local column `UPDATE`, column-level `REFERENCES`, and `TRIGGER` authority. It also exercises a real enqueue under a `SELECT, INSERT`-only application role. Production store calls under the unsafe effective roles must fail before tenant binding or data SQL.

Current TDD lineage for the UPDATE defect is static RED `f5208b7b124248eae1e9855ec771734abe0e3ffb`, realistic PostgreSQL specimen `638dac99442cd4fcb00c9e63cb97b1c695bfea3e`, and causal source/test repair `b354a569c1bb3857be33cf65612c9260c2a77f8e`.

ADR 0031 is the decision record. It remains Proposed until the exact repaired final head executes this PostgreSQL/container specimen and repository quality gates successfully.

## References

PostgreSQL Global Development Group. (2026a). *Privileges*. In *PostgreSQL 16 documentation*. https://www.postgresql.org/docs/16/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *SELECT*. In *PostgreSQL 16 documentation*. https://www.postgresql.org/docs/16/sql-select.html

PostgreSQL Global Development Group. (2026c). *System administration functions: Advisory lock functions*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026d). *Row security policies*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html
