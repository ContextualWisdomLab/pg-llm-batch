# Legacy PostgreSQL extension retirement after direct-SQL retrieval

## Status and maturity

- **Decision maturity:** PLANNED — Issue #103.
- **Dependency:** begin only from a protected-main result that has integrated or superseded #101's direct-SQL provider-retrieval retirement.
- **Documentation maturity:** ACTIVE-PR #93 until this canonical documentation branch integrates.
- **Shipped behavior:** none. Protected main still bundles the legacy PostgreSQL extension packages/preload compatibility needed by existing volumes.

## Context

The legacy database-side provider retriever used `pg_cron` plus `pgsql-http`. ACTIVE-PR #101 removes that provider-network authority and stops fresh databases from creating those extensions, while intentionally retaining package/preload compatibility so an existing data volume that already records the extensions can start and run the cleanup safely.

That compatibility stage is necessary for upgrades but is not the desired steady state. After the direct-SQL provider path is gone, keeping scheduler/network extension packages and `pg_cron` preload configuration in fresh images expands database runtime authority without a supported product need. Removing them in the same step as #101 would be unsafe: an upgraded volume can still contain extension-owned objects and unrelated cron jobs that require the extension binaries during startup and migration.

## Decision drivers

1. Remove database-side network/scheduler runtime authority that no longer has a supported product path.
2. Preserve upgradeability and rollback for existing PostgreSQL volumes.
3. Never use `DROP ... CASCADE` to erase unknown extension dependants in order to make an image build green.
4. Preserve historical `gateway_retrieval_logs` and all lifecycle/request/audit data.
5. Keep automatic provider reconciliation (#102) independent and routed through the validated Python provider boundary.
6. Produce evidence for both fresh-install and legacy-volume upgrade paths before package/preload removal.

## Considered alternatives

### A. Remove packages and preload in #101

Rejected. Existing volumes may still have `http` or `pg_cron` installed. Removing their binaries/preload before the database can start and execute a reviewed migration can turn a security cleanup into an availability or recovery incident.

### B. Keep the packages permanently

Rejected. Once no supported repository path depends on the extensions, permanent installation/preload retains unnecessary network/scheduler code and weakens least-privilege deployment evidence.

### C. Drop extensions with `CASCADE`

Rejected. `CASCADE` can destroy unrelated extension-owned objects or user jobs and would hide dependency discovery instead of proving a safe migration.

### D. Explicit two-stage existing-volume migration, then image/runtime removal

Accepted target. Compatibility remains until a bounded migration proves that the retired job and helper objects are gone and that no unrelated objects depend on the extensions; only then are preload/settings/packages removed.

## Decision

Issue #103 shall implement a two-stage retirement boundary after #101 is protected-main truth.

### Stage 1 — inspect and migrate an existing volume

The migration must detect, without mutating first:

- whether `http` and `pg_cron` extensions are installed;
- whether the exact retired `batch-result-retrieval` cron job still exists;
- whether any legacy helper functions from the retired provider path remain;
- whether unrelated cron jobs or extension-owned/dependent objects would block safe removal; and
- whether historical `gateway_retrieval_logs` and package-owned lifecycle/request/audit data are present and intact.

The mutation may proceed only after the retired job is unscheduled and the legacy helper functions are absent. Extension removal must fail closed when unrelated dependants remain. The supported migration must use dependency-aware explicit drops; it must not use `DROP EXTENSION ... CASCADE` as a shortcut.

### Stage 2 — remove runtime/package authority

Only after Stage 1 has been proven on an upgraded legacy fixture may a subsequent image/runtime change:

- remove `pg_cron` from `shared_preload_libraries`;
- remove obsolete `cron.*` PostgreSQL configuration;
- remove the `pg_cron` package from the bundled PostgreSQL image;
- remove the pgsql-http package after proving no supported repository path references its SQL objects; and
- remove health/doctoring assumptions that those extensions exist while preserving required readiness for `database`, `pg_tiktoken`, and `com_config`.

Fresh installations and existing-volume migrations are separate acceptance paths. A fresh database should never acquire the retired extensions merely to exercise migration compatibility.

## Architecture and authority consequences

Provider network authority remains in `BatchAPIClient` / `DurableBatchAPIClient`. This decision does not create a replacement provider client in PostgreSQL. Issue #102 remains the independent automatic-reconciliation target through the validated Python credential, destination, retry, response-size, identity, and lifecycle boundaries.

No new persistence is introduced by this decision, so the protected-main ERD must not invent a migration-state table merely to document #103. If implementation later requires durable migration bookkeeping, that is a separate schema decision requiring an ADR, migration/rollback contract, and ERD update.

## Security and privacy impact

The steady-state benefit is least privilege: fresh images no longer carry database-side HTTP/scheduler components that have no supported purpose. Migration evidence may contain object names, counts, versions, and dependency identities, but must not export provider credentials, DSNs, prompts, provider bodies, or secret values. Privileged extension removal is an auditable operator action and must not be presented as application-role capability.

## Compatibility and migration requirements

- Existing volumes must be able to start on the compatibility image before cleanup.
- Interrupted migration must have a deterministic resume/recovery path.
- Rollback must distinguish pre-removal compatibility rollback from post-package-removal image rollback.
- `gateway_retrieval_logs` must survive the migration.
- Unrelated cron jobs and extension dependants must block removal instead of being deleted.
- A clean fresh database and an upgraded legacy-volume fixture are both required test targets.

## Verification and acceptance

Implementation acceptance requires, on the exact source head and then on the integrated protected head where applicable:

1. a realistic PostgreSQL fixture containing the retired extensions, exact retired cron job, helper objects, and preserved historical log/lifecycle data;
2. RED evidence that package/preload removal without migration is unsafe or fails the upgrade fixture;
3. successful detection and ordered cleanup of only the retired repository-owned objects;
4. explicit failure when an unrelated cron job or extension dependant remains;
5. proof that no migration path executes `DROP EXTENSION ... CASCADE`;
6. successful restart after cleanup with `pg_cron` removed from `shared_preload_libraries` and obsolete `cron.*` configuration absent;
7. successful clean fresh-database startup without creating the retired extensions;
8. repository CI, 100% owned statement/branch coverage and public-docstring gates where code is added, security/SAST, container build, SBOM/provenance and Release Acceptance evidence required by live policy; and
9. documentation/doctoring that separately explains fresh install, existing-volume upgrade, interrupted recovery, and rollback.

## Rollback and recovery

Before Stage 2 package/preload removal, rollback may return to the compatibility image while preserving the migrated data volume. After Stage 2, rollback to an image that requires `pg_cron` preload must not be implied safe without checking the resulting database configuration and extension catalog. Recovery procedures must be tested against an interrupted Stage 1 and a completed Stage 1 followed by image replacement.

## Non-goals

- restoring direct-SQL provider HTTP;
- implementing #102 automatic reconciliation;
- deleting historical retrieval logs;
- deleting unrelated cron jobs or extension-owned objects;
- claiming zero-downtime upgrade without explicit evidence; or
- inventing package-owned persistence solely to represent migration progress.

## References

PostgreSQL Global Development Group. (n.d.). *CREATE EXTENSION*. PostgreSQL documentation. https://www.postgresql.org/docs/current/sql-createextension.html

PostgreSQL Global Development Group. (n.d.). *DROP EXTENSION*. PostgreSQL documentation. https://www.postgresql.org/docs/current/sql-dropextension.html

PostgreSQL Global Development Group. (n.d.). *Dependency tracking*. PostgreSQL documentation. https://www.postgresql.org/docs/current/ddl-depend.html

ContextualWisdomLab. (2026, August 10). *[Security] Retire legacy PostgreSQL cron/http packages after upgrade migration* (Issue #103). `pg-llm-batch`.