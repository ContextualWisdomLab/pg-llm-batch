# PostgreSQL logging privacy and container-routing boundary

## Scope

`docker/postgres/postgresql.conf.custom` is an optional operator-applied PostgreSQL profile. The bundled image copies the file but does not automatically include it in the running cluster configuration. This document therefore defines the supported profile contract without claiming that every deployment enables it.

pg-llm-batch may process prompts, responses, identifiers, provider configuration, lifecycle evidence, and secret-management operations. The package preserves those authorized business values in their owning data path; it avoids unnecessary secondary copies in database logs and statistics rather than applying blanket masking.

## Root causes

Earlier monitoring examples mixed observability with content retention. They enabled broad SQL statement logging, representative query-text collection, connection-event logging, high-volume temp/autovacuum events, optional timing/function statistics, and extra transaction metadata without a concrete purpose or measured budget. The privacy repair disabled those default copies, but the profile still routed logs to PostgreSQL-managed `csvlog` files with `logging_collector = on`. PostgreSQL file rotation limits individual files; **rotation is not retention**. In a container deployment that left aggregate deletion and capacity outside the package while making PostgreSQL itself the log-file owner.

The reviewed profile now separates two concerns:

1. PostgreSQL decides which bounded operational events exist and which content classes remain disabled.
2. The container runtime or platform logging pipeline owns persisted log routing, rotation, bounded retention, export, encryption, access, residency, backup, and deletion.

## Content-safe baseline

The package profile keeps ordinary SQL statement text and bind values out of persistent server logs by default:

- `log_statement = none`;
- `log_min_duration_statement = -1` and `log_min_duration_sample = -1`;
- statement and transaction sample rates are `0`;
- `log_duration = off`;
- `log_parameter_max_length = 0` and `log_parameter_max_length_on_error = 0`;
- `log_min_error_statement = PANIC` and `log_error_verbosity = terse`;
- `log_connections = off` and `log_disconnections = off`; and
- `pg_stat_statements.track = none`, with utility/planning/save disabled.

Connection lifecycle logging remains an explicit **opt-in**. When a deployment deliberately enables CSV output, PostgreSQL's CSV schema includes a fixed **client host:port** field, so the result can contain **client network metadata** even when `log_hostname = off`. A structured destination must therefore not be represented as network-identifier-free.

## Container-native log routing

The supported container profile uses:

```text
logging_collector = off
log_destination = stderr
```

PostgreSQL supports `stderr` as a server-message destination. With the collector disabled, the package does not create a PostgreSQL-managed persistent log-file lifecycle. A **container runtime** can capture standard output/error and pass it to a configured **logging driver** or cluster logging agent. Docker exposes per-container/daemon logging-driver controls, and Kubernetes documents stdout/stderr as the standard container log stream while requiring operators to configure the surrounding storage and rotation architecture.

This does not make logging storage-free. Docker logging drivers and Kubernetes node/cluster logging still require deployment-owned capacity and **bounded retention**. The package does not select a universal retention period, legal hold, residency, export destination, or backup policy.

A deployment that deliberately requires `csvlog`, `jsonlog`, syslog, or PostgreSQL-managed files may provide a reviewed overlay. Such an overlay must enable `logging_collector` coherently when required, define storage capacity and deletion, and preserve the content-safe settings above unless separately authorized. PostgreSQL documents `logging_collector` as a server-start parameter, so changing `logging_collector` requires a **PostgreSQL restart**, not a configuration reload. Rollback from the stderr profile to collector-backed file logging therefore crosses the same restart boundary and must not silently restore broad SQL/bind logging.

## High-volume log event boundary

`log_temp_files = -1` keeps temporary-file logging disabled by default. PostgreSQL documents that zero logs all **temporary file names and sizes** when each file is deleted; deployments may opt in with a reviewed positive threshold or, for short-lived diagnosis, zero.

`log_autovacuum_min_duration = 10min` remains active at PostgreSQL 16's documented default threshold. It can emit records for autovacuum actions that meet or exceed that duration and for documented skipped-autovacuum conditions; it is therefore not a disabled or wholly opt-in event class. Lowering the threshold, or using zero to log all autovacuum actions, is an additional opt-in diagnostic that requires an explicit expected-volume, storage, retention, and response budget. A deployment that must disable autovacuum action logging entirely can use `-1` under its own reviewed operability policy.

## Timing and function-statistics boundary

`track_io_timing = off` and `track_wal_io_timing = off` keep platform-dependent clock-read work disabled until a deployment measures the host with `pg_test_timing` and accepts the **timing overhead**. These metrics are **opt-in** rather than universal product telemetry.

`track_functions = none` keeps function-call timing/count collection disabled by default. PostgreSQL's cumulative **statistics collection** has execution cost, and **function statistics** should be enabled only when they answer a concrete diagnostic question and representative testing shows acceptable **overhead**. Disabling them again requires no business-data migration.

## Commit-timestamp metadata boundary

`track_commit_timestamp = off` preserves PostgreSQL's documented **default is off** behavior. Enabling `track_commit_timestamp` is a **server start** choice that writes additional transaction information under `pg_commit_ts`. It remains an **opt-in** facility for a defined replication or forensic consumer; it is not package-owned durable audit retention.

## Query-statistics preload boundary

`pg_stat_statements` is absent from `shared_preload_libraries`. PostgreSQL documents that the module consumes **shared memory** whenever it is loaded, **even if `pg_stat_statements.track = none`**. The generic profile therefore leaves query statistics genuinely disabled and uses `compute_query_id = auto`.

A deployment that needs query-level statistics must add the module to `shared_preload_libraries`, **restart PostgreSQL**, create the extension only in the intended database, enable a reviewed tracking mode, restrict representative query-text access, and accept the shared-memory/query-ID cost. Setting tracking back to `none` stops collection but does not reclaim preload memory until the module is removed and PostgreSQL is restarted.

## Live activity residual boundary

The profile intentionally leaves `track_activities = on` and bounds `track_activity_query_size` to 1024 bytes. `pg_stat_activity` can therefore expose current/recent **query text** as **volatile** server state. PostgreSQL privileges such as `pg_read_all_stats` can widen cross-session visibility. Deployments must restrict and audit that privileged access. This residual is why the product claims persistent statement/query-stat retention is disabled by default, not that query text can never exist in PostgreSQL memory.

## Compliance and governance boundary

No PostgreSQL logging setting proves SOC 2, ISO/IEC 27001, PCI DSS, CSAP, privacy-law compliance, or any certification. Event scope, privileged access, retention, deletion, export, and incident handling are risk-based deployment decisions. The package favors purpose-bound authorization, least privilege, selective disclosure, and auditable access over indiscriminate duplication of business content.

## Test-first evidence and acceptance

Issue #120 is implemented from a deterministic RED regression: the protected profile had `logging_collector = on`, while the new contract required `off` plus `stderr`. The production change preserves the already-tested SQL/bind/connection/query-statistics privacy settings while changing only the operational log ownership path.

The documentation semantics were also locked test-first after review: exact-head CI at RED commit `64ddd4a9ba66d3c13481192e9398ffd92f00efa4` failed because the operator guide did not yet state the restart-only collector boundary or distinguish active 10-minute autovacuum logging from disabled temporary-file logging. This revision corrects those semantics against PostgreSQL 16 primary documentation.

The repository suite verifies the configuration semantics on Python 3.10, 3.12, and 3.14, while container/Compose, security, SAST, package, coverage, and exact-source governance remain independent final gates. The container-build job also starts the built PostgreSQL image with this operator profile explicitly, proves `config_file`, `logging_collector`, and `log_destination` at runtime, verifies no PostgreSQL-managed current log file exists, emits a fixed non-sensitive server warning, and requires that warning to appear through `docker logs`.

## Rollback and recovery

If stderr/platform logging is unsuitable for a specific environment, use a deployment-owned overlay rather than changing the package baseline blindly. The overlay must name the destination, collector requirement, capacity, rotation, **bounded retention**, deletion, access, encryption, export, backup, and recovery procedure. Rollback must preserve `log_statement = none`, bind-value suppression, connection-event opt-in, disabled query-statistics collection, and the high-volume/performance opt-ins unless a separate reviewed decision explicitly changes them.

If unnecessary content or client-network copies are discovered, stop the relevant logging path, preserve only evidence required by the incident/legal process, rotate or revoke exposed credentials where relevant, and execute the deployment's deletion/backup-expiry process for unnecessary copies.

## APA 7 references

Docker, Inc. (2026). *Configure logging drivers*. Docker Docs. https://docs.docker.com/engine/logging/configure/

Kubernetes Authors. (2026). *Logging architecture*. Kubernetes Documentation. https://kubernetes.io/docs/concepts/cluster-administration/logging/

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Error reporting and logging*. https://www.postgresql.org/docs/16/runtime-config-logging.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Run-time statistics*. https://www.postgresql.org/docs/16/runtime-config-statistics.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: pg_stat_statements—Track statistics of SQL planning and execution*. https://www.postgresql.org/docs/16/pgstatstatements.html
