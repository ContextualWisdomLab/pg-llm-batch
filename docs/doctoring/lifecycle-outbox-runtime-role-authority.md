# Lifecycle outbox runtime role authority

The lifecycle outbox application connection is a tenant-scoped append-only DML identity, not a database-maintenance identity. Runtime admission must establish both effective and session-level PostgreSQL authority. DSN text is not authorization evidence, and a superficially safe `CURRENT_USER` is insufficient when the authenticated `SESSION_USER` can later select or administer an unsafe role.

PostgreSQL evaluates ordinary SQL privileges against `CURRENT_USER`, but `SET ROLE` permission continues to be evaluated against `SESSION_USER`. The runtime guard therefore treats the live role-selection closure as authority: `CURRENT_USER`, `SESSION_USER`, every role the session user can select with `SET ROLE`, and every role for which the session user holds `MEMBER WITH ADMIN OPTION` and can therefore make selectable.

Before the package binds `pg_llm_batch.tenant_scope` or executes outbox data SQL, one fail-closed catalog query must prove:

- the canonical outbox still has both `relrowsecurity` and `relforcerowsecurity` enabled;
- no role in the effective/session-selectable/administerable closure is `SUPERUSER` or `BYPASSRLS`;
- no role in that closure owns the outbox or can exercise, select, or administer the owner through `USAGE`, `SET`, or `MEMBER WITH ADMIN OPTION`;
- no role in that closure has `TRUNCATE`, `DELETE`, or table/column `UPDATE` privilege on the outbox;
- no role in that closure has table-level or column-level `REFERENCES` privilege; and
- no role in that closure has `TRIGGER` privilege.

Inert membership remains allowed when it cannot be inherited, selected, or made selectable through admin authority. PostgreSQL 16+ distinguishes membership from inherited `USAGE`, `SET ROLE`, and membership administration. A least-privilege login wrapper may therefore `SET ROLE` to a separate application role, provided neither identity nor any session-selectable/administerable role carries authority outside the append-only envelope.

`TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` are separated from the application connection for different reasons. `TRUNCATE` is a whole-table destructive operation outside ordinary row filtering. `DELETE` and `UPDATE` remain RLS-filtered, but that does not make tenant-local erasure or rewrite compatible with append-only durable publication intent. `REFERENCES` can create external dependency authority. `TRIGGER` permits executable behavior to be attached to the relation.

Replay preflight no longer uses `SELECT ... FOR UPDATE`, because PostgreSQL requires `UPDATE` privilege for a locking `SELECT`. Same-identity package serialization uses `pg_catalog.pg_advisory_xact_lock(bigint)` on a deterministic tenant/event coordination key, followed by a plain tenant-qualified `SELECT`. The signed 64-bit SHA-256 projection is coordination metadata only. Durable identity remains `(tenant_scope, evidence_id)` plus exact row revalidation; a coordination-key collision can delay unrelated work but cannot merge durable identities.

## Deployment guidance

Use distinct connection identities for runtime and administration. The runtime login/session identity should have no path to owner, destructive, mutation, relation-programming, or RLS-bypass roles. Grant the application role only the package-required `SELECT` and `INSERT` privileges on the outbox. Keep schema ownership, migrations, recovery reconciliation, explicit lifecycle retention/deletion, and relation programming on separate operator connections.

Do not authenticate a runtime connection as a superuser or owner and rely on `SET ROLE` as a downgrade. PostgreSQL allows the session user to regain/select roles according to its original session authority. Likewise, an initially authenticated superuser can change `SESSION_USER` with `SET SESSION AUTHORIZATION` and later reset to the original identity. The package cannot prove away that hidden initial administrative authority after deliberate session-authorization changes; such connections are outside the supported runtime deployment boundary.

A representative operator audit should inspect both current/session identities and the session-selectable/administerable closure rather than only one role record. The package's executable query is authoritative; the following shape illustrates the closure to review:

```sql
SELECT
    current_user,
    session_user,
    selectable_role.rolname,
    pg_catalog.pg_has_role(session_user, selectable_role.oid, 'SET') AS session_can_set,
    pg_catalog.pg_has_role(
        session_user,
        selectable_role.oid,
        'MEMBER WITH ADMIN OPTION'
    ) AS session_can_admin,
    selectable_role.rolsuper,
    selectable_role.rolbypassrls,
    selectable_role.oid = outbox.relowner AS is_owner,
    pg_catalog.pg_has_role(selectable_role.oid, outbox.relowner, 'USAGE') AS owner_usage,
    pg_catalog.pg_has_role(selectable_role.oid, outbox.relowner, 'SET') AS owner_set,
    pg_catalog.pg_has_role(
        selectable_role.oid,
        outbox.relowner,
        'MEMBER WITH ADMIN OPTION'
    ) AS owner_admin,
    pg_catalog.has_table_privilege(
        selectable_role.oid,
        outbox.oid,
        'TRUNCATE'
    ) AS can_truncate,
    pg_catalog.has_table_privilege(
        selectable_role.oid,
        outbox.oid,
        'DELETE'
    ) AS can_delete,
    pg_catalog.has_any_column_privilege(
        selectable_role.oid,
        outbox.oid,
        'UPDATE'
    ) AS can_update,
    pg_catalog.has_any_column_privilege(
        selectable_role.oid,
        outbox.oid,
        'REFERENCES'
    ) AS can_reference,
    pg_catalog.has_table_privilege(
        selectable_role.oid,
        outbox.oid,
        'TRIGGER'
    ) AS can_trigger
FROM pg_catalog.pg_class AS outbox
CROSS JOIN pg_catalog.pg_roles AS selectable_role
WHERE outbox.oid = pg_catalog.to_regclass('public.llm_context_lifecycle_outbox')
  AND (
      selectable_role.rolname = current_user
      OR selectable_role.rolname = session_user
      OR pg_catalog.pg_has_role(session_user, selectable_role.oid, 'SET')
      OR pg_catalog.pg_has_role(
          session_user,
          selectable_role.oid,
          'MEMBER WITH ADMIN OPTION'
      )
  );
```

For an admitted connection, the outbox's RLS flags are both true and every role in this closure is free of the unsafe authority above.

Do not repair a failing runtime identity by weakening forced RLS, granting `UPDATE` for `FOR UPDATE`, suppressing the package guard, or authenticating as an administrator and downgrading only `CURRENT_USER`. Revoke/separate the conflicting authority or use a dedicated least-privilege login/runtime-role chain.

## Executable acceptance

`tests/smoke_context_lifecycle_outbox_effective_role_authority.sh` continues to prove ordinary tenant visibility, inert owner-membership compatibility, raw `BYPASSRLS`, owner control, `TRUNCATE`, tenant-local `DELETE`/`UPDATE`, column-level `REFERENCES`, and `TRIGGER` authority.

`tests/smoke_context_lifecycle_outbox_session_user_authority.sh` adds the authenticated-session boundary. It creates a non-superuser login that can `SET ROLE` to a safe application role and also to the outbox owner. PostgreSQL first proves the effective role is safe-looking while the session login can still select the owner and alter forced-RLS authority. Package access under that effective role must then fail before tenant/data SQL. A separate non-superuser login whose only selectable application role remains safe is the positive control.

Fresh lineage is static/realistic RED `d3d19da69af08d05eb6c4f7589003161c51a6988`, production repair `89114ce0c6fb7cc27b03f492e8f4fe37693f2195`, and unit-contract alignment `41c74ca599e744aff67407dc883975708cba76df`.

ADR 0031 is the decision record. It remains Proposed until one exact repaired final head executes the PostgreSQL/container specimen and all repository quality gates successfully.

## References

PostgreSQL Global Development Group. (2026a). *SET ROLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026b). *System information functions and operators*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026c). *Role membership*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026d). *GRANT*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026e). *SET SESSION AUTHORIZATION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-session-authorization.html
