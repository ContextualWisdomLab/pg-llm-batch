# Operability

## Existing-volume legacy extension retirement

`docker/postgres/migrations/retire_legacy_provider_extensions.sql` is the bounded operator procedure for removing the retired `http` and `pg_cron` extensions from an existing database. It does **not** remove operating-system packages or edit `shared_preload_libraries`; those are separate image and host-configuration changes after every supported existing volume has completed this database migration.

### Preconditions

Before running the retirement migration:

1. take and verify a restorable database backup;
2. deploy the Python provider lifecycle and reconciliation path that replaced database-side provider networking;
3. run `docker/postgres/init/03_cron_batch_retrieval.sql` successfully so the package-owned `batch-result-retrieval` schedule and exact retired helper definitions are removed;
4. inventory `cron.job` and migrate or remove every operator-owned schedule;
5. investigate any remaining function with one of these signatures instead of deleting it automatically:
   - `public.cron_fetch_batch_results()`;
   - `public.import_batch_results_jsonl(uuid,text,text)`;
   - `public.get_secret_value(text)`;
   - `public.get_config_value(text)`; and
6. verify that applications no longer depend on objects owned by `http` or `pg_cron`.

Recommended preflight queries:

```sql
SELECT jobid, jobname, schedule, command FROM cron.job ORDER BY jobid;
SELECT to_regprocedure('public.cron_fetch_batch_results()');
SELECT to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)');
SELECT to_regprocedure('public.get_secret_value(text)');
SELECT to_regprocedure('public.get_config_value(text)');
SELECT extname FROM pg_extension WHERE extname IN ('http', 'pg_cron');
```

### Execution

Run the reviewed file with `ON_ERROR_STOP` enabled:

```bash
psql "$PG_LLM_BATCH_DSN" --set ON_ERROR_STOP=1 \
  --file docker/postgres/migrations/retire_legacy_provider_extensions.sql
```

The migration executes in one transaction and sets `SET LOCAL lock_timeout = '5s'`. It refuses to proceed while any cron job or retired helper signature remains. Extension removal uses only:

```sql
DROP EXTENSION IF EXISTS http RESTRICT;
DROP EXTENSION IF EXISTS pg_cron RESTRICT;
```

`CASCADE` is intentionally forbidden. PostgreSQL therefore rejects the drop when an unreviewed dependent object exists instead of deleting application or operator state.

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
- **`RESTRICT` dependency failure:** identify the dependent object with PostgreSQL catalog tools, decide whether it must be migrated, and rerun after that reviewed change. Do not replace `RESTRICT` with `CASCADE`.
- **Connection or process loss:** PostgreSQL rolls back the open transaction. Reconnect, repeat the preflight, and rerun.

A successful migration is idempotent: replay sees both extensions absent and commits without changing application state. A failed attempt is also safely rerunnable after its documented blocker is corrected because the transaction commits neither extension drop independently.

### Rollback boundary

The migration preserves application evidence but cannot recreate an extension, its configuration, or an operator schedule. Operational rollback therefore means restoring the verified backup or reinstalling the exact reviewed extension versions and explicitly recreating required operator-owned schedules. Never restore the retired package-owned provider network function or schedule after the Python provider boundary has become authoritative.

The live container contract is `tests/smoke_legacy_sql_cleanup.sh`; it covers substituted helpers, marker-preserving modified helpers, independent cron authority, preservation of `gateway_retrieval_logs`, successful retirement, and idempotent replay.
