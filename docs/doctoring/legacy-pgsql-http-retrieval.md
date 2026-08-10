# Legacy pgsql-http batch retrieval retirement

## Decision

The bundled direct-SQL provider retriever is retired. Provider-facing batch I/O belongs to the package-owned Python `BatchAPIClient` boundary and, when durable lifecycle evidence is required, `DurableBatchAPIClient`. The file `docker/postgres/init/03_cron_batch_retrieval.sql` is retained as an idempotent cleanup seam so a fresh database does not create the old job and an existing volume can replay the same file to remove it.

This is a fail-closed retirement, not a rewrite of the network client in PL/pgSQL. A replacement SQL client would have to duplicate destination validation, credential handling, remote-resource validation, bounded response/retry behavior, lifecycle ordering, and persistence semantics already owned by the Python path. Doing so would create two security authorities for the same provider operation.

The fresh-install contract is simple: fresh databases no longer create the `pg_cron` or `http` extensions. They retain only package-required `pgcrypto` plus the existing optional `pg_tiktoken` creation seam. This removes database-side scheduling/network authority from new installations while preserving the Python provider boundary. For existing volumes, Docker initialization does not rewrite previously installed extensions; they remain until an operator performs a separately reviewed migration. The PostgreSQL image packages remain temporarily available for upgrade compatibility and for cleanup of an already-installed `pg_cron` job; package/preload removal requires separate existing-volume startup and rollback evidence rather than being coupled to this fail-closed retirement.

## RCA

Protected main scheduled `batch-result-retrieval` every minute and called `cron_fetch_batch_results()`. That function read a base URL from `com_config`, decoded a non-encrypted secret inside PostgreSQL, issued credential-bearing `http_get` calls, parsed provider payloads, and wrote request/batch completion state.

The first failing boundary is identity and authority, not a missing retry. The SQL loop selected `llm_batches.batch_uuid` and sent that local batch UUID as the provider batch identifier. The durable provider path instead records validated provider identifiers under endpoint-qualified `llm_remote_batch_jobs`; protected main does not provide a reviewed local-batch-to-remote-job binding that would make those identifiers interchangeable. Treating a local UUID as a provider ID is therefore a false integration contract.

The credential boundary is also incompatible. The SQL helper could only decode the base64-obfuscated form of `com_secrets`; it returned `NULL` for Fernet-protected values because the decryption key is intentionally application-side. Base64 is representation, not encryption. Reintroducing direct SQL retrieval by weakening the Fernet boundary or adding another database-visible decryption authority would be a security regression.

Finally, the Python client already owns validated gateway authority, remote resource identifiers, bounded HTTP responses, retry/replay semantics, and provider-error handling. `DurableBatchAPIClient` adds ordered lifecycle persistence on top of that client rather than creating a second network implementation. The smallest correction is therefore to remove the unsupported SQL network path and stop enabling its database capabilities for fresh installations.

A later cleanup audit found a second identity defect: exact cron-job matching was followed by unconditional `DROP FUNCTION IF EXISTS` calls on four generic public signatures. An operator may legitimately replace a legacy function while retaining the same signature. Signature-only deletion would then destroy unrelated operator code. The cleanup now treats a same-signature function as untrusted until its current catalog definition still matches the retired helper's characteristic implementation.

## Bounded implementation

`03_cron_batch_retrieval.sql` now performs only cleanup:

- if `pg_cron` is installed, enumerate visible jobs whose name is exactly `batch-result-retrieval` **and** whose command is exactly `SELECT cron_fetch_batch_results();`, then call `cron.unschedule` by numeric job ID; this avoids deleting an unrelated same-name job;
- resolve each legacy helper with `to_regprocedure(...)`, inspect its current `pg_catalog.pg_proc` / language metadata, and remove it only when the signature plus language, volatility, invoker-security shape, and characteristic retired implementation markers still match;
- if a same-signature function has been replaced or materially changed, the helper-removal block fails closed with a fixed error instead of deleting it. That substituted function requires manual review;
- never call `http_get`, never construct an `Authorization` header, never read provider credentials, and never create a replacement cron schedule; and
- preserve historical `gateway_retrieval_logs` data. The cleanup does not drop that table or any lifecycle/request table.

The exact job-removal block and helper-identity block are separate SQL statements. With the documented `psql -v ON_ERROR_STOP=1 -f ...` invocation and normal psql autocommit, the exact legacy job unschedule is committed before a later same-signature helper mismatch raises its fail-closed exception. This ordering prioritizes stopping future unsafe provider calls while refusing destructive function deletion whose identity cannot be proven.

`01_extensions.sql` now omits `CREATE EXTENSION` for both `pg_cron` and `http` on fresh databases. The container still carries their operating-system packages for backward compatibility with existing volumes in this slice. That staged distinction is intentional: removing a library from an image while an upgraded data directory still records the corresponding extension/preload dependency can make recovery harder than first removing the unsafe application authority.

No schema is invented to paper over the missing local/remote identity relation. No provider credential, lifecycle row, request payload, or existing log row is rewritten.

## Existing-volume remediation

Docker entrypoint initialization scripts run only when the PostgreSQL data directory is first initialized, so replacing the image is not sufficient evidence that an existing volume stopped the old job. Apply the cleanup during a maintenance window using the same job owner that created the cron entry, or a PostgreSQL superuser. pg_cron applies row-level visibility/ownership rules to job management, so a different unprivileged role may not be able to see or remove the job.

From an exact checked-out release containing this repair, run the cleanup file against the target database, for example:

```sh
psql "$PG_LLM_BATCH_DSN" -v ON_ERROR_STOP=1 \
  -f docker/postgres/init/03_cron_batch_retrieval.sql
```

Then verify that no future invocation of the exact legacy job remains:

```sql
SELECT jobid, jobname, schedule, command
FROM cron.job
WHERE jobname = 'batch-result-retrieval'
  AND command = 'SELECT cron_fetch_batch_results();';
```

The acceptance result is zero rows for that exact name-and-command identity. An unrelated job that merely reuses the same name is outside this cleanup boundary.

Also inspect the legacy helper signatures:

```sql
SELECT
    to_regprocedure('public.cron_fetch_batch_results()') AS cron_fetch,
    to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)') AS importer,
    to_regprocedure('public.get_secret_value(text)') AS secret_reader,
    to_regprocedure('public.get_config_value(text)') AS config_reader;
```

On an unmodified legacy installation all four values must be `NULL` after successful cleanup. If the cleanup instead refuses a same-signature function because its current definition no longer matches the retired implementation, do **not** bypass the guard or drop it by signature alone. Confirm first that the exact legacy cron job is absent, then perform manual review of the substituted function's ownership, callers, body, dependencies, and intended lifecycle before deciding whether it should remain or be removed.

Unscheduling prevents future starts; it does not retroactively erase a provider call that was already running before remediation began. During incident remediation, inspect `cron.job_run_details` and provider-side request evidence for an in-flight or recently completed run. If a credential might have crossed an unintended boundary, rotate it through the normal secret-management path rather than storing a replacement key in SQL.

The cleanup intentionally does not drop `gateway_retrieval_logs`. Existing audit/history rows remain available to operators. A fresh database no longer creates the unused table through this file.

## Supported provider path

Use `BatchAPIClient` for host-owned lifecycle persistence or `DurableBatchAPIClient` when pg-llm-batch should persist ordered provider lifecycle observations. Credentials should be resolved through the configured secret-store seam. Endpoint aliases and provider resource IDs remain host/provider inputs only after the package validation boundary accepts them.

Do not resurrect the SQL retriever merely to restore automatic polling. A future scheduler must invoke the validated application boundary (directly or through the repository's orchestrated service contract), preserve exact remote identity, and prove bounded credentials, network destination, retries, response size, cancellation, observability, and rollback semantics before it can replace this cleanup.

## Acceptance and rollback

Acceptance is falsifiable:

1. repository tests prove the bundled SQL contains no credential-bearing provider HTTP and no `cron.schedule` call;
2. fresh initialization does not create `pg_cron` or `http`, while required `pgcrypto` and optional `pg_tiktoken` behavior remain intact;
3. replaying the cleanup on a database with the exact legacy job leaves zero matching name-and-command rows in `cron.job`;
4. unmodified legacy helper definitions are removed, while a same-signature function whose identity no longer matches the retired implementation fails closed and is preserved for manual review;
5. historical retrieval-log data is not dropped; and
6. ordinary provider operations continue through `BatchAPIClient` / `DurableBatchAPIClient`, not through PostgreSQL HTTP.

Rollback must not restore the retired SQL network path. If this change exposes a missing operational scheduler, keep provider polling host-driven while designing a replacement against the same validated application boundary. Restoring the prior cron script would knowingly reintroduce the false local/remote identity and weaker secret authority that caused this retirement. Existing volumes keep their installed extension binaries in this stage, so rollback does not require recreating extensions on fresh databases merely to preserve old-volume recovery.

## References

Citus Data. (2025). *pg_cron: Run periodic jobs in PostgreSQL* [Computer software]. GitHub. https://github.com/citusdata/pg_cron

PostgreSQL Global Development Group. (2026). *pgcrypto — cryptographic functions* (PostgreSQL 18 documentation). https://www.postgresql.org/docs/current/pgcrypto.html

Ramsey, P. (n.d.). *pgsql-http: HTTP client for PostgreSQL* [Computer software]. GitHub. Retrieved August 10, 2026, from https://github.com/pramsey/pgsql-http
