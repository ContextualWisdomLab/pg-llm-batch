# Lifecycle outbox runtime role authority

The lifecycle outbox application connection is a tenant-scoped append-only DML identity, not a database-maintenance, role-administration, database-creation, replication, privilege-delegation, or privileged-definer identity. Runtime admission must establish both effective/session-level PostgreSQL role authority and the live canonical RLS policy semantics. DSN text is not authorization evidence, and a superficially safe `CURRENT_USER` is insufficient when the authenticated `SESSION_USER` can later select or administer an unsafe role.

PostgreSQL evaluates ordinary SQL privileges against `CURRENT_USER`, but `SET ROLE` permission continues to be evaluated against `SESSION_USER`. The runtime guard therefore treats the live role-selection closure as authority: `CURRENT_USER`, `SESSION_USER`, every role the session user can select with `SET ROLE`, and every role for which the session user holds `MEMBER WITH ADMIN OPTION` and can therefore make selectable.

Migration 0009 proves the canonical policy only at its own transaction boundary. A later owner/operator DDL sequence can keep both `relrowsecurity` and `relforcerowsecurity` enabled while dropping and recreating the canonical policy under the same name with wider predicates. PostgreSQL stores policy command scope, permissive/restrictive mode, target roles, `USING`, and `WITH CHECK` semantics in `pg_policy`; the policy name and relation flags do not freeze those semantics. Runtime therefore re-proves the live policy before binding tenant state or executing outbox data SQL.

Before the package binds `pg_llm_batch.tenant_scope` or executes outbox data SQL, one fail-closed catalog query must prove:

- the canonical outbox still has both `relrowsecurity` and `relforcerowsecurity` enabled;
- exactly one policy exists on the outbox and it is `plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2`;
- that policy remains all-command, permissive, and `PUBLIC`;
- its parser-normalized `USING` and `WITH CHECK` predicates are exactly `tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)`;
- any tracked normal function/operator dependency remains within the reviewed PostgreSQL `current_setting(text, boolean)` and text-equality boundary;
- no role in the effective/session-selectable/administerable closure is `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, or `BYPASSRLS`;
- no role in that closure owns the outbox or can exercise, select, or administer the owner through `USAGE`, `SET`, or `MEMBER WITH ADMIN OPTION`;
- no role in that closure has table- or column-level `SELECT WITH GRANT OPTION` or `INSERT WITH GRANT OPTION` on the outbox;
- no role in that closure has `TRUNCATE`, `DELETE`, or table/column `UPDATE` privilege on the outbox;
- no role in that closure has table-level or column-level `REFERENCES` privilege;
- no role in that closure has `TRIGGER` privilege; and
- no selectable/administerable role can execute a non-system-schema `SECURITY DEFINER` routine whose owner is a superuser, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, the exact/inherited outbox owner, holds outbox `SELECT`/`INSERT` grant option, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, or `TRIGGER`, or holds `ADMIN OPTION` over a role that directly or through an all-`SET TRUE` path carries the same forbidden operator/relation authority.

Inert membership remains allowed when it cannot be inherited, selected, or made selectable through admin authority. PostgreSQL 16+ distinguishes membership from inherited `USAGE`, `SET ROLE`, and membership administration. A least-privilege login wrapper may therefore `SET ROLE` to a separate application role, provided neither identity nor any session-selectable/administerable role carries authority outside the append-only envelope.

`CREATEDB` and `CREATEROLE` are administrative attributes rather than application DML. PostgreSQL permits a `CREATEDB` principal to create databases. `CREATEROLE` permits creating roles and administering roles for which the principal has the required administration authority. Role attributes are not inherited merely because ordinary membership is inherited, but a session with `SET` authority can become a role carrying those attributes. The runtime contract therefore rejects them anywhere in the same session-selectable/administerable closure. This is a least-privilege and bounded-context decision, not a claim that either attribute automatically bypasses RLS.

The same boundary applies when `CREATEROLE` is reachable through executable definer code. PostgreSQL executes a `SECURITY DEFINER` routine with the function owner's authority rather than the caller's. A non-superuser function owner carrying `CREATEROLE` can therefore execute role-administration statements even when the runtime login itself is `NOCREATEROLE`. PostgreSQL's `CREATE FUNCTION` documentation specifically addresses security-definer functions that create roles by requiring an explicit `createrole_self_grant` setting when their behavior depends on how the created role is granted. The package does not parse a mutable function body to decide whether that authority is harmless; callable user-schema definers are admitted only when their owners remain inside the same reviewed runtime authority envelope. This is role-administration separation, not an assertion that `CREATEROLE` itself bypasses RLS.

A callable definer owner does not need `CREATEROLE` to redistribute a role when it already has `ADMIN OPTION` on that role. PostgreSQL defines `ADMIN` membership authority separately from `INHERIT` and `SET`: an administrator can grant the administered role onward even when its own membership is `INHERIT FALSE, SET FALSE`. `SET ROLE` itself is prohibited inside a `SECURITY DEFINER` function, but that is not a defense against this delegation path. The function can execute `GRANT` under the owner's authority, return, and leave the caller with a new `SET TRUE` role path. Runtime admission therefore follows each callable definer owner's `MEMBER WITH ADMIN OPTION` targets and rejects a target that directly carries forbidden authority or can `SET ROLE` through an all-`SET TRUE` path to a role that does. The package does not auto-revoke that membership or function execution edge; operator-owned authorization repair remains required.

`REPLICATION` is a separate cluster-level authority. PostgreSQL requires it (or superuser) for replication-mode connections and for creating or dropping replication slots, and describes the attribute as very highly privileged. The exclusion here is not a claim that `REPLICATION` automatically bypasses RLS; PostgreSQL can still apply publisher row-security policies for a non-superuser replication role without `BYPASSRLS`. The application contract simply has no need for replication connection/slot authority, so co-locating it with tenant DML would violate least privilege and the operator/runtime separation.

That rule also applies to executable definer owners. A `NOREPLICATION` runtime login can have schema `USAGE` and routine `EXECUTE` on a user-schema `SECURITY DEFINER` function whose owner is a separate `REPLICATION` role. Because the routine executes with the owner's privileges, PostgreSQL's SQL-callable `pg_create_physical_replication_slot` can then create a physical replication slot even though the caller itself has no `REPLICATION` attribute. Runtime admission therefore inspects `definer_role.rolreplication` in the same callable-definer catalog predicate and fails before tenant binding or outbox data SQL. This is indirect replication operator authority, not an RLS-bypass claim.

`SELECT WITH GRANT OPTION` and `INSERT WITH GRANT OPTION` are authorization-delegation capabilities, not additional data operations required by the application. PostgreSQL lets a grant-option holder grant the corresponding privilege onward. An ordinary delegated role remains subject to RLS, so this is not treated as an automatic RLS bypass. The boundary is narrower: the runtime identity must not be able to manufacture additional outbox readers or writers. `pg_catalog.has_any_column_privilege(..., '... WITH GRANT OPTION')` covers whole-table and column-level forms without parsing ACL text.

`TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, and `TRIGGER` are separated from the application connection for different reasons. `TRUNCATE` is a whole-table destructive operation outside ordinary row filtering. `DELETE` and `UPDATE` remain RLS-filtered, but that does not make tenant-local erasure or rewrite compatible with append-only durable publication intent. `REFERENCES` can create external dependency authority. `TRIGGER` permits executable behavior to be attached to the relation. These same privileges remain forbidden when they are carried by the owner of a callable user-schema `SECURITY DEFINER` routine, because executing the routine uses that owner's authority.

Replay preflight no longer uses `SELECT ... FOR UPDATE`, because PostgreSQL requires `UPDATE` privilege for a locking `SELECT`. Same-identity package serialization uses `pg_catalog.pg_advisory_xact_lock(bigint)` on a deterministic tenant/event coordination key, followed by a plain tenant-qualified `SELECT`. The signed 64-bit SHA-256 projection is coordination metadata only. Durable identity remains `(tenant_scope, evidence_id)` plus exact row revalidation; a coordination-key collision can delay unrelated work but cannot merge durable identities.

## Deployment guidance

Use distinct connection identities for runtime, database/role administration, replication, privilege delegation, privileged definer execution, and other maintenance. The runtime login/session identity should have no path to owner, destructive, mutation, relation-programming, RLS-policy modification, database-creation, role-administration, replication, DML grant-option, RLS-bypass, or callable privileged user-schema definer authority. Grant the application role only non-grantable package-required `SELECT` and `INSERT` privileges on the outbox. Keep schema ownership, policy ownership, migrations, recovery reconciliation, explicit lifecycle retention/deletion, database creation, role administration, replication, privilege delegation, privileged definer routines, and relation programming on separate operator connections.

Do not authenticate a runtime connection as a superuser, database creator, role administrator, owner, replication identity, DML delegator, or privileged-definer gateway and rely on `SET ROLE` as a downgrade. PostgreSQL allows the session user to regain/select roles according to its session authority. Likewise, an initially authenticated superuser can change `SESSION_USER` with `SET SESSION AUTHORIZATION` and later reset to the original identity. The package cannot prove away hidden initial administrative, replication, delegation, or privileged-definer authority after deliberate session-authority changes; those connections are outside the supported runtime deployment boundary.

A representative operator audit should inspect both current/session identities and the session-selectable/administerable closure rather than only one role record. The package's executable query is authoritative; the following shape illustrates the direct role closure to review. Executable-definer authority must be reviewed separately through `pg_proc`, function ownership, schema `USAGE`, routine `EXECUTE`, owner role attributes including `rolcreaterole` and `rolreplication`, owner membership administration, administered-role `SET` reachability, and owner/reachable relation privileges; the package query performs that proof in the same admission round trip.

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
    selectable_role.rolcreatedb,
    selectable_role.rolcreaterole,
    selectable_role.rolreplication,
    selectable_role.rolbypassrls,
    selectable_role.oid = outbox.relowner AS is_owner,
    pg_catalog.pg_has_role(selectable_role.oid, outbox.relowner, 'USAGE') AS owner_usage,
    pg_catalog.pg_has_role(selectable_role.oid, outbox.relowner, 'SET') AS owner_set,
    pg_catalog.pg_has_role(
        selectable_role.oid,
        outbox.relowner,
        'MEMBER WITH ADMIN OPTION'
    ) AS owner_admin,
    pg_catalog.has_any_column_privilege(
        selectable_role.oid,
        outbox.oid,
        'SELECT WITH GRANT OPTION'
    ) AS can_delegate_select,
    pg_catalog.has_any_column_privilege(
        selectable_role.oid,
        outbox.oid,
        'INSERT WITH GRANT OPTION'
    ) AS can_delegate_insert,
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

The policy catalog should also show one exact canonical tenant policy rather than merely the expected name:

```sql
SELECT
    polname,
    polcmd,
    polpermissive,
    polroles,
    pg_catalog.pg_get_expr(polqual, polrelid, false) AS using_expression,
    pg_catalog.pg_get_expr(polwithcheck, polrelid, false) AS with_check_expression
FROM pg_catalog.pg_policy
WHERE polrelid = pg_catalog.to_regclass('public.llm_context_lifecycle_outbox');
```

For an admitted connection, both RLS flags are true, the sole policy has the reviewed tenant predicate, every role in the selectable/administerable closure is free of the unsafe direct authority above, and no callable non-system-schema `SECURITY DEFINER` route reintroduces or redistributes forbidden relation, role-administration, or replication authority through its owner.

Do not repair a failing runtime identity or policy by weakening forced RLS, granting `UPDATE` for `FOR UPDATE`, keeping DML grant options for operational convenience, suppressing the package guard, authenticating as an administrator or replication role and downgrading only `CURRENT_USER`, allowing a callable `CREATEROLE`/`REPLICATION`/destructive/admin-delegating definer for convenience, or accepting same-name policy drift. Revoke/separate the conflicting authority or restore the reviewed policy through the operator-owned migration/reconciliation path.

## Executable acceptance

`tests/smoke_context_lifecycle_outbox_effective_role_authority.sh` continues to prove ordinary tenant visibility, inert owner-membership compatibility, raw `BYPASSRLS`, owner control, `TRUNCATE`, tenant-local `DELETE`/`UPDATE`, column-level `REFERENCES`, and `TRIGGER` authority.

`tests/smoke_context_lifecycle_outbox_session_user_authority.sh` covers the authenticated-session boundary. It creates a non-superuser login that can `SET ROLE` to a safe application role and also to the outbox owner. PostgreSQL first proves the effective role is safe-looking while the session login can still select the owner and alter forced-RLS authority. Package access under that effective role must then fail before tenant/data SQL. A separate non-superuser login whose only selectable application role remains safe is the positive control. The same smoke creates dedicated `REPLICATION`, `CREATEDB`, and `CREATEROLE` login principals with only outbox `SELECT, INSERT`; it directly demonstrates the replication, database-creation, and role-creation capabilities and requires runtime admission to reject each administrative attribute before tenant binding/data SQL.

`tests/smoke_context_lifecycle_outbox_grant_option_authority.sh` creates an otherwise-minimal runtime login with outbox `SELECT, INSERT WITH GRANT OPTION`, grants `SELECT` onward to a separate ordinary role, requires that recipient to execute a real outbox read, and then requires package access through the grant-capable runtime identity to fail before tenant binding or data SQL. The delegated role remains an ordinary RLS subject; the specimen proves usable delegation authority rather than claiming RLS bypass.

`tests/smoke_context_lifecycle_outbox_role_admin_delegation_authority.sh` covers membership and executable-definer delegation. It proves `ADMIN OPTION` can redistribute DML directly and through a `SET TRUE` role chain, proves a callable superuser-owned definer can expose cross-tenant reads, proves an ordinary non-owner definer with only outbox `TRUNCATE` can empty the durable outbox, and proves a non-superuser `CREATEROLE` definer can let an otherwise ordinary `NOCREATEROLE` runtime login create a cluster role. Package admission must fail closed for each callable privileged-definer route before tenant binding or data SQL.

`tests/smoke_context_lifecycle_outbox_security_definer_replication_authority.sh` covers the separate replication-administration edge. It creates an ordinary `LOGIN NOREPLICATION` runtime role and a `NOLOGIN REPLICATION` function owner, exposes a callable `SECURITY DEFINER` routine owned by that replication principal, proves the ordinary caller can execute `pg_create_physical_replication_slot` through the routine and that the slot exists, then requires package admission to fail closed before tenant binding or outbox data SQL.

`tests/smoke_context_lifecycle_outbox_security_definer_admin_authority.sh` covers the definer-owner membership-administration edge without giving that function owner `CREATEROLE` or direct destructive relation privileges. The owner receives `ADMIN OPTION` over an `INHERIT FALSE, SET FALSE` bridge role; that bridge has `SET TRUE` to a separate outbox `TRUNCATE` role. The callable definer grants the bridge to an ordinary runtime login, the login then traverses the `SET` chain and empties the outbox, and the test revokes the newly delegated membership before invoking package access. Admission must still reject the latent callable authority, proving the guard follows the definer owner's administration graph rather than merely detecting the already-materialized caller membership.

`tests/smoke_context_lifecycle_outbox_runtime_rls_policy_authority.sh` exercises post-migration policy drift. It first proves the canonical policy exposes only tenant A to a least-privilege runtime role, then recreates the same canonical policy name with `USING (true) WITH CHECK (true)` while leaving RLS enabled and forced. Raw SQL must then see both tenant rows, proving the catalog drift is materially widening. Package access must fail before tenant binding or data SQL instead of trusting the policy name or migration history.

Authenticated-session lineage is static/realistic RED `d3d19da69af08d05eb6c4f7589003161c51a6988`, production repair `89114ce0c6fb7cc27b03f492e8f4fe37693f2195`, and unit-contract alignment `41c74ca599e744aff67407dc883975708cba76df`.

Live-policy lineage is static RED `645d655e2cca11c89e0fa7bcd50fac9f52f1898e`, real PostgreSQL RED `5309b8f5631ae1d4570bfb0fed9b21839b88d923`, container-lane wiring `c99f9a17624df8610d259ffec0276a6add9bdaba`, and causal runtime repair `434e7a5c269dc9780b9160580683d7467ece3565`.

Replication-authority lineage is static RED `52e22ab3fd2824efa7fc0b9ada5f8cd3f0626b8b`, real PostgreSQL/container RED `9879fcf1ee0aea9c5eb91d1f1021c9f0efe15487`, and causal production repair `555d9ebfdd407f7d6b5f6805338c9da236d2a309`.

Database/role-administration lineage is static RED `89ae7fa9a0b2723c636477f4a3a49d2af8336658`, PostgreSQL/container RED specimen `358ce8d08d6ab815efff66f98751e186106c84f7`, and causal production repair `03a683e422d036e06327850adb0840560b7db207`.

DML-delegation lineage is static RED `c9dd5189488d6f5acfdfe1d5919e88dd593c3398`, PostgreSQL RED specimen `4f890a3da639bea9ef7444265dcc670d9a914791`, executable delegation refinement `e50674cc534ea402b99f38f4c3319bddb93e2d52`, CI wiring `8a51ec8a96e1e47f659fc7235f5d118686d5a1c9`, and causal production repair `146e521a439c038e0b418a7c93c114140ad7fc1f`.

Executable-definer role-administration lineage is static RED `6ca1edf1e8405550235deb2a2809876bce373e13`, causal production repair `9921f551d6a64770b93bd769ab599c2cdd1bae0d`, and real PostgreSQL specimen `554189734a8ef257ba9a496f984866f2fea03709`.

Executable-definer replication lineage is static RED `d8f95092b08124063d636537831503710eefaf51`, causal production repair `e2116cf9a87938cac67b41ba17dd4a4e09b5ec48`, executable PostgreSQL specimen `c5c9761583ef91a34d6f3ca5fb1c7d86c935037a`, and PostgreSQL/container CI wiring `439e22b0df22c43af6c5855779128642b9f2a7a4`.

Executable-definer membership-administration lineage is static RED `8ae6de147bc9b1746f25d4b29f6de43b6ed7d4a8`, causal query repair `646fadfbefe6c93e9255face270594861695309e`, SQL-grouping correction `988ed9b611bc442891e9769ae86a0caf63764ab3`, real PostgreSQL transitive delegation specimen `cba5f92a62f91c6aecee2c2c68f9f1cfcda25e6c`, and PostgreSQL/container CI wiring `fb6c3bba7aad728290f0be27e9591888c0584cb6`.

ADR 0031 remains the broader runtime-role separation decision; ADR 0032 records the delegable and executable privilege boundary. ADR 0032 remains Proposed until one exact repaired final head executes the PostgreSQL/container specimens and all repository quality gates successfully.

## References

PostgreSQL Global Development Group. (2026a). *SET ROLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026b). *System information functions and operators*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026c). *Role membership*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026d). *GRANT*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026e). *SET SESSION AUTHORIZATION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-session-authorization.html

PostgreSQL Global Development Group. (2026f). *Row security policies*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026g). *pg_policy*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026h). *CREATE POLICY*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026i). *CREATE ROLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createrole.html

PostgreSQL Global Development Group. (2026j). *pg_roles*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/view-pg-roles.html

PostgreSQL Global Development Group. (2026k). *Logical replication security*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/logical-replication-security.html

PostgreSQL Global Development Group. (2026l). *Role attributes*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/role-attributes.html

PostgreSQL Global Development Group. (2026m). *Privileges*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-priv.html

PostgreSQL Global Development Group. (2026n). *CREATE FUNCTION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createfunction.html

PostgreSQL Global Development Group. (2026o). *System administration functions*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-admin.html
