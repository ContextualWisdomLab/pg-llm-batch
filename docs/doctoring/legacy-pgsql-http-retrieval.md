# Legacy pgsql-http batch retrieval retirement

## Decision

The bundled direct-SQL provider retriever is retired. Provider-facing batch I/O belongs to the package-owned Python `BatchAPIClient` boundary and, when durable lifecycle evidence is required, `DurableBatchAPIClient`. The file `docker/postgres/init/03_cron_batch_retrieval.sql` is retained as an idempotent cleanup seam so a fresh database does not create the old job and an existing volume can replay the same file to remove it.

This is a fail-closed retirement, not a rewrite of the network client in PL/pgSQL. A replacement SQL client would have to duplicate destination validation, credential handling, remote-resource validation, bounded response/retry behavior, lifecycle ordering, and persistence semantics already owned by the Python path. Doing so would create two security authorities for the same provider operation.

## RCA

Protected main scheduled `batch-result-retrieval` every minute and called `cron_fetch_batch_results()`. That function read a base URL from `com_config`, decoded a non-encrypted secret inside PostgreSQL, issued credential-bearing `http_get` calls, parsed provider payloads, and wrote request/batch completion state.

The first failing boundary is identity and authority, not a missing retry. The SQL loop selected `llm_batches.batch_uuid` and sent that local batch UUID as the provider batch identifier. The durable provider path instead records validated provider identifiers under endpoint-qualified `llm_remote_batch_jobs`; protected main does not provide a reviewed local-batch-to-remote-job binding that would make those identifiers interchangeable. Treating a local UUID as a provider ID is therefore a false integration contract.

The credential boundary is also incompatible. The SQL helper could only decode the base64-obfuscated form of `com_secrets`; it returned `NULL` for Fernet-protected values because the decryption key is intentionally application-side. Base64 is representation, not encryption. Reintroducing direct SQL retrieval by weakening the Fernet boundary or adding another database-visible decryption authority would be a security regression.

Finally, the Python client already owns validated gateway authority, remote resource identifiers, bounded HTTP responses, retry/replay semantics, and provider-error handling. `DurableBatchAPIClient` adds ordered lifecycle persistence on top of that client rather than creating a second network implementation. The smallest correction is therefore to remove the unsupported SQL network path.

## Bounded implementation

`03_cron_batch_retrieval.sql` now performs only cleanup:

- if `pg_cron` is installed, enumerate visible jobs whose name is exactly `batch-result-retrieval` and call `cron.unschedule` by numeric job ID;
- remove `cron_fetch_batch_results()`, `import_batch_results_jsonl(UUID, TEXT, TEXT)`, `get_secret_value(TEXT)`, and `get_config_value(TEXT)` if those legacy helpers exist;
- never call `http_get`, never construct an `Authorization` header, never read provider credentials, and never create a replacement cron schedule;
- preserve historical `gateway_retrieval_logs` data. The cleanup does not drop that table or any lifecycle/request table; and
- leave the `http` extension itself unchanged in this slice because current health/container contracts are owned by separate active work. Extension pruning is a distinct integration decision after those owners settle.

No schema is invented to paper over the missing local/remote identity relation. No provider credential, lifecycle row, request payload, or existing log row is rewritten.

## Existing-volume remediation

Docker entrypoint initialization scripts run only when the PostgreSQL data directory is first initialized, so replacing the image is not sufficient evidence that an existing volume stopped the old job. Apply the cleanup during a maintenance window using the same job owner that created the cron entry, or a PostgreSQL superuser. pg_cron applies row-level visibility/ownership rules to job management, so a different unprivileged role may not be able to see or remove the job.

From an exact checked-out release containing this repair, run the cleanup file against the target database, for example:

```sh
psql "$PG_LLM_BATCH_DSN" -v ON_ERROR_STOP=1 \
  -f docker/postgres/init/03_cron_batch_retrieval.sql
```

Then verify that no future legacy invocation remains:

```sql
SELECT jobid, jobname, schedule, command
FROM cron.job
WHERE jobname = 'batch-result-retrieval';
```

The acceptance result is zero rows. Also verify the removed functions are absent:

```sql
SELECT
    to_regprocedure('cron_fetch_batch_results()') AS cron_fetch,
    to_regprocedure('import_batch_results_jsonl(uuid,text,text)') AS importer,
    to_regprocedure('get_secret_value(text)') AS secret_reader,
    to_regprocedure('get_config_value(text)') AS config_reader;
```

All four values must be `NULL`.

Unscheduling prevents future starts; it does not retroactively erase a provider call that was already running before remediation began. During incident remediation, inspect `cron.job_run_details` and provider-side request evidence for an in-flight or recently completed run. If a credential might have crossed an unintended boundary, rotate it through the normal secret-management path rather than storing a replacement key in SQL.

The cleanup intentionally does not drop `gateway_retrieval_logs`. Existing audit/history rows remain available to operators. A fresh database no longer creates the unused table through this file.

## Supported provider path

Use `BatchAPIClient` for host-owned lifecycle persistence or `DurableBatchAPIClient` when pg-llm-batch should persist ordered provider lifecycle observations. Credentials should be resolved through the configured secret-store seam. Endpoint aliases and provider resource IDs remain host/provider inputs only after the package validation boundary accepts them.

Do not resurrect the SQL retriever merely to restore automatic polling. A future scheduler must invoke the validated application boundary (directly or through the repository's orchestrated service contract), preserve exact remote identity, and prove bounded credentials, network destination, retries, response size, cancellation, observability, and rollback semantics before it can replace this cleanup.

## Acceptance and rollback

Acceptance is falsifiable:

1. repository tests prove the bundled SQL contains no credential-bearing provider HTTP and no `cron.schedule` call;
2. replaying the cleanup on a database with the legacy named job leaves zero matching rows in `cron.job` and removes the four helper functions;
3. historical retrieval-log data is not dropped; and
4. ordinary provider operations continue through `BatchAPIClient` / `DurableBatchAPIClient`, not through PostgreSQL HTTP.

Rollback must not restore the retired SQL network path. If this change exposes a missing operational scheduler, keep provider polling host-driven while designing a replacement against the same validated application boundary. Restoring the prior cron script would knowingly reintroduce the false local/remote identity and weaker secret authority that caused this retirement.

## References

Citus Data. (2025). *pg_cron: Run periodic jobs in PostgreSQL* [Computer software]. GitHub. https://github.com/citusdata/pg_cron

PostgreSQL Global Development Group. (2026). *pgcrypto — cryptographic functions* (PostgreSQL 18 documentation). https://www.postgresql.org/docs/current/pgcrypto.html

Ramsey, P. (n.d.). *pgsql-http: HTTP client for PostgreSQL* [Computer software]. GitHub. Retrieved August 10, 2026, from https://github.com/pramsey/pgsql-http
