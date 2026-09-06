# Lifecycle outbox runtime role authority

The lifecycle outbox application identity is a tenant-scoped DML identity, not a database-maintenance identity. Runtime admission follows PostgreSQL effective `CURRENT_USER`; DSN text and login identity are not authorization evidence after `SET ROLE`.

Before the package binds `pg_llm_batch.tenant_scope` or executes outbox data SQL, the live role/relation query must prove all of the following at the same admission point:

- `CURRENT_USER` is neither `SUPERUSER` nor `BYPASSRLS`;
- `public.llm_context_lifecycle_outbox` still has both `relrowsecurity` and `relforcerowsecurity` enabled;
- `CURRENT_USER` is not the table owner and cannot exercise, select, or administer the owner role through `USAGE`, `SET`, or `MEMBER WITH ADMIN OPTION`;
- the role has no `TRUNCATE` privilege on the outbox;
- the role has no table-level or column-level `REFERENCES` privilege on the outbox; and
- the role has no `TRIGGER` privilege on the outbox.

Inert owner-role membership granted with `INHERIT FALSE, SET FALSE` and without admin option is not rejected merely because the membership edge exists. PostgreSQL 16+ distinguishes membership from immediately inherited privileges and `SET ROLE` authority.

`TRUNCATE`, `REFERENCES`, and `TRIGGER` are separated from the application identity for different reasons. PostgreSQL row security does not apply to whole-table operations such as `TRUNCATE`, so a normal non-owner role with that privilege can remove every tenant row while forced RLS remains configured. `REFERENCES` can be granted to individual columns as well as the whole table; PostgreSQL warns that a foreign-key creator can arrange for enforcement to invoke arbitrary functions with table-owner privileges. `TRIGGER` permits executable behavior to be attached to the relation and PostgreSQL warns that such triggers execute with the privileges of users modifying the table.

The runtime guard therefore uses `pg_catalog.has_table_privilege` for `TRUNCATE` and `TRIGGER`, and `pg_catalog.has_any_column_privilege(..., 'REFERENCES')` so both table-wide and column-specific reference authority fail closed. A table-only `REFERENCES` check is insufficient.

Do not replace this boundary with a blanket “SELECT and INSERT only” rule. The package compare-and-swap path uses `SELECT ... FOR UPDATE`; PostgreSQL requires `UPDATE` privilege on at least one column for that lock. Ordinary DML remains subject to forced RLS and the package's tenant-qualified SQL contract. The restriction here targets whole-table or relation-programming authority that is outside, or can program around, that boundary.

## Deployment guidance

Use a distinct operator/migration role for schema ownership, grants, triggers, constraints, indexes, migrations, and recovery reconciliation. The runtime application role should receive only the DML needed by the package and must not receive the three authorities above, directly or through an inherited role.

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
    pg_catalog.has_table_privilege(
        current_user,
        c.oid,
        'TRUNCATE'
    ) AS can_truncate,
    pg_catalog.has_any_column_privilege(
        current_user,
        c.oid,
        'REFERENCES'
    ) AS can_reference,
    pg_catalog.has_table_privilege(
        current_user,
        c.oid,
        'TRIGGER'
    ) AS can_trigger
FROM pg_catalog.pg_roles AS r
JOIN pg_catalog.pg_class AS c
  ON c.oid = pg_catalog.to_regclass('public.llm_context_lifecycle_outbox')
WHERE r.rolname = current_user;
```

For an admitted application identity, the two RLS flags are `true` and every authority/bypass boolean is `false`.

Do not “repair” a failing runtime identity by weakening forced RLS or suppressing the package guard. Revoke or separate the conflicting grant/role path, then re-run the exact application-role and PostgreSQL/container acceptance tests. Privileged operator DDL or GRANT changes racing after a successful admission query remain an administrative boundary; application isolation does not claim protection from a concurrently malicious database administrator.

## Executable acceptance

`tests/smoke_context_lifecycle_outbox_effective_role_authority.sh` contains the real PostgreSQL acceptance surface. It must prove ordinary tenant visibility, inert owner-membership compatibility, raw `BYPASSRLS` visibility, owner ability to remove forced-owner enforcement, RLS-exempt `TRUNCATE` authority, column-level `REFERENCES` authority, and `TRIGGER` attachment authority. Production store calls under the corresponding unsafe effective roles must fail before tenant binding/data SQL.

ADR 0031 is the decision record. It remains Proposed until the exact repaired head executes this PostgreSQL/container specimen and repository quality gates successfully.

## References

PostgreSQL Global Development Group. (2026a). *Privileges*. In *PostgreSQL 16 documentation*. https://www.postgresql.org/docs/16/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *Row security policies*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026c). *System information functions and operators*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026d). *Role membership*. In *PostgreSQL 16 documentation*. https://www.postgresql.org/docs/16/role-membership.html
