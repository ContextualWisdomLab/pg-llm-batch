# Operability

## Existing-volume legacy extension retirement

`docker/postgres/migrations/retire_legacy_provider_extensions.sql` is the bounded operator procedure for removing the retired `http` and `pg_cron` extensions from an existing database. It does **not** remove operating-system packages or edit `shared_preload_libraries`; those are separate image and host-configuration changes after every supported existing volume has completed this database migration.

### Preconditions

Before running the retirement migration:

1. take and verify a restorable database backup;
2. deploy the Python provider lifecycle and reconciliation path that replaced database-side provider networking;
3. run `docker/postgres/init/03_cron_batch_retrieval.sql` successfully so the package-owned `batch-result-retrieval` schedule and exact retired helper definitions are removed;
4. when `pg_cron` and `cron.job` exist, inventory every row and migrate or remove every operator-owned schedule;
5. investigate any remaining function with one of these signatures instead of deleting it automatically:
   - `public.cron_fetch_batch_results()`;
   - `public.import_batch_results_jsonl(uuid,text,text)`;
   - `public.get_secret_value(text)`;
   - `public.get_config_value(text)`;
6. inventory `pg_depend` for the `http` and `pg_cron` extensions. Any explicit `DEPENDS ON EXTENSION` dependency (`deptype = 'x'`) requires operator disposition, and any table-like extension member (`deptype = 'e'`) outside the expected `pg_cron` `cron` schema boundary must be treated as application/operator state; and
7. verify that applications no longer depend on objects owned by `http` or `pg_cron`.

Recommended preflight queries below are written for `psql`. The job-list query is deliberately conditional so a database without `pg_cron` or `cron.job` does not fail merely while inventorying an already-retired surface:

```sql
SELECT (
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension
        WHERE extname = 'pg_cron'
    )
    AND to_regclass('cron.job') IS NOT NULL
) AS cron_job_available
\gset
\if :cron_job_available
SELECT jobid, jobname, schedule, command FROM cron.job ORDER BY jobid;
\endif

SELECT to_regprocedure('public.cron_fetch_batch_results()');
SELECT to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)');
SELECT to_regprocedure('public.get_secret_value(text)');
SELECT to_regprocedure('public.get_config_value(text)');
SELECT extname FROM pg_extension WHERE extname IN ('http', 'pg_cron');

SELECT ext.extname,
       dep.deptype,
       pg_catalog.pg_describe_object(dep.classid, dep.objid, dep.objsubid)
           AS dependent_object
FROM pg_catalog.pg_depend AS dep
JOIN pg_catalog.pg_extension AS ext
  ON dep.refclassid = 'pg_catalog.pg_extension'::pg_catalog.regclass
 AND dep.refobjid = ext.oid
LEFT JOIN pg_catalog.pg_class AS relation
  ON dep.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
 AND dep.objid = relation.oid
LEFT JOIN pg_catalog.pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE ext.extname IN ('http', 'pg_cron')
  AND (
      dep.deptype = 'x'
      OR (
          dep.deptype = 'e'
          AND relation.relkind IN ('r', 'p', 'f', 'm', 'v', 'S')
          AND (ext.extname = 'http' OR namespace.nspname <> 'cron')
      )
  )
ORDER BY ext.extname, dep.deptype, dependent_object;
```

The final dependency query must return no rows before retirement. It intentionally does not classify every normal extension-owned function, type, or internal `pg_cron` relation as application state; it identifies the auto-dropped dependency classes that this migration treats as requiring explicit review.

### Execution

Run the reviewed file with `ON_ERROR_STOP` enabled:

```bash
psql "$PG_LLM_BATCH_DSN" --set ON_ERROR_STOP=1 \
  --file docker/postgres/migrations/retire_legacy_provider_extensions.sql
```

The migration executes in one transaction and sets `SET LOCAL lock_timeout = '5s'`. It refuses to proceed while any cron job or retired helper signature remains, while an unexpected table-like object is an extension member, or while any explicit auto-extension dependency remains. Extension removal uses only:

```sql
DROP EXTENSION IF EXISTS http RESTRICT;
DROP EXTENSION IF EXISTS pg_cron RESTRICT;
```

`CASCADE` is intentionally forbidden. `RESTRICT` remains the final PostgreSQL dependency boundary, but it is not sufficient by itself to preserve extension members or objects marked `DEPENDS ON EXTENSION`, because those objects are removed with the extension. The explicit `pg_depend` preflight therefore rejects those auto-drop cases before either extension drop is attempted.

### Acceptance checks

After success, verify:

```sql
SELECT count(*) AS retired_extension_count
FROM pg_extension
WHERE extname IN ('http', 'pg_cron');

SELECT to_regclass('public.gateway_retrieval_logs') AS preserved_evidence_table;
```

The expected extension count is `0`; `gateway_retrieval_logs` must still resolve when it existed before migration. The migration never drops that application-owned evidence table, an application schema, or another table.

### Fail-closed recovery

- **Lock timeout:** no partial retirement is committed. Identify the blocking session, follow the site's change-control process, and rerun the same migration after contention is resolved.
- **Package-owned schedule still present:** rerun `03_cron_batch_retrieval.sql`, inspect its failure, and retry retirement only after the exact schedule is absent.
- **Operator cron job remains:** preserve it until its owner migrates or removes it. Do not rename it merely to bypass the preflight.
- **Retired helper signature remains:** compare the live function definition with the historical package definition. A substituted or modified function is operator-owned and must be dispositioned manually.
- **Unexpected extension member remains:** identify the object with the `pg_depend` query. If it is application/operator state that was accidentally enrolled, preserve it and detach it from the extension only through a reviewed `ALTER EXTENSION ... DROP <member>` change after ownership is proven. If it is intentionally extension-owned, do not retire that extension until the dependency is migrated.
- **Explicit `DEPENDS ON EXTENSION` object remains:** migrate or otherwise disposition the object. Use `NO DEPENDS ON EXTENSION` only when a reviewed ownership decision proves the object must survive independently; do not strip the dependency merely to bypass the guard.
- **`RESTRICT` dependency failure:** identify the remaining dependent object with PostgreSQL catalog tools, decide whether it must be migrated, and rerun after that reviewed change. Do not replace `RESTRICT` with `CASCADE`.
- **Connection or process loss:** PostgreSQL rolls back the open transaction. Reconnect, repeat the preflight, and rerun.

A successful migration is idempotent: replay sees both extensions absent and commits without changing application state. A failed attempt is also safely rerunnable after its documented blocker is corrected because the transaction commits neither extension drop independently.

### Rollback boundary

The migration preserves application evidence but cannot recreate an extension, its configuration, or an operator schedule. Operational rollback therefore means restoring the verified backup or reinstalling the exact reviewed extension versions and explicitly recreating required operator-owned schedules. Never restore the retired package-owned provider network function or schedule after the Python provider boundary has become authoritative.

The live container contract is `tests/smoke_legacy_sql_cleanup.sh`; it covers substituted helpers, marker-preserving modified helpers, independent cron authority, an application table enrolled as an extension member, an explicit `DEPENDS ON EXTENSION` routine, preservation of `gateway_retrieval_logs`, successful retirement, and idempotent replay.
