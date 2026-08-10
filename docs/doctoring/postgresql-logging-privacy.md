# PostgreSQL logging privacy boundary

## Scope

`docker/postgres/postgresql.conf.custom` is an **optional operator-applied configuration surface**. The current container copies the file but does not automatically include it in the running PostgreSQL cluster. This doctoring therefore describes the safety contract for deployments that deliberately apply the file; it does not claim protected `main` currently enables these settings.

pg-llm-batch can process prompts, provider configuration, identifiers, lifecycle evidence, and secret-management operations. SQL statement text and bind values can therefore contain personal, confidential, or credential-bearing content. The package must preserve the business data itself for authorized batch work; the risk treatment is to avoid unnecessary secondary copies in logs/statistics rather than destructively masking production data.

## Root cause

The former example enabled `log_statement = 'all'`, slow/sample statement logging, transaction statement sampling, verbose error output, and `pg_stat_statements` collection/persistence, and described blanket SQL logging plus jurisdiction-specific multi-year retention as if they were generally required for compliance. PostgreSQL 16 explicitly warns that logged statements can reveal sensitive data and plaintext passwords, and extended-query protocol statement logging can include bind parameter values. PostgreSQL also documents that `pg_stat_statements` stores representative query text, with normalization caveats. The old example therefore made disclosure and retention a side effect of generic monitoring guidance rather than an explicit data-governance decision.

## Decision

The reviewed baseline keeps ordinary SQL statement text and bind values out of server logs and makes query-text statistics collection opt-in:

- `log_statement = none`;
- `log_min_duration_statement = -1` and `log_min_duration_sample = -1`;
- statement and transaction sample rates are `0`;
- `log_duration = off` to avoid high-volume per-statement events by default;
- `log_parameter_max_length = 0` and `log_parameter_max_length_on_error = 0`;
- `log_min_error_statement = PANIC` so ordinary errors do not add failing statement text;
- `log_error_verbosity = terse` so PostgreSQL omits `DETAIL`, `HINT`, `QUERY`, and `CONTEXT` error fields; and
- `pg_stat_statements.track = none`, planning/utility tracking off, and `save = off` so preloading the module does not silently start representative-query retention if the extension is present.

Connection, disconnection, checkpoint, lock-wait, temporary-file, autovacuum, I/O, WAL, function, commit-timestamp, query-ID, table/index, and activity-state telemetry remain available. This is not a claim that every remaining monitoring surface is content-free: live activity tracking has the separate residual boundary below.

This is **selective disclosure**, not blanket masking. The source data remains available to the authorized application/database path. If an embedding organization has a genuine requirement for content-bearing database audit logs or query-level `pg_stat_statements`, it must enable that separately under a purpose-specific authorization, least-privilege access model, retention/deletion schedule, encryption/storage boundary, access audit, legal basis, and incident procedure.

## Live `pg_stat_activity` residual boundary

The baseline deliberately leaves `track_activities = on` because current-session state is useful for operational diagnosis. PostgreSQL documents that `pg_stat_activity.query` exposes the current or most recent **query text** for a backend and that the text is truncated according to `track_activity_query_size`; this example keeps that bound at 1024 bytes. This activity record is **volatile** server state rather than the persistent server-log or `pg_stat_statements` store removed above, but it can still contain prompt, identifier, configuration, or credential-management content while a session is observable.

Access is therefore part of the trust boundary. PostgreSQL restricts visibility of security-sensitive activity fields for other users; superusers and roles with `pg_read_all_stats` can see information for all sessions. Deployments must grant those roles only to purpose-authorized operators and audit privileged access. If a deployment cannot accept live query-text visibility even under that access model, it may set `track_activities = off`, but that deliberately sacrifices current-command/activity diagnostics and must be evaluated as an operability tradeoff rather than presented as a free privacy switch.

This residual is why the configuration and doctoring say **persistent SQL/bind-value logging and query-stat retention are disabled by default**, not that PostgreSQL has no in-memory query text anywhere.

## `pg_stat_statements` residual boundary

The optional file still preloads `pg_stat_statements`, but the protected-main initialization script does not create the extension and this baseline sets collection to `none`. A deployment can deliberately override that. PostgreSQL documents that the extension retains representative query text; literal constants are commonly normalized but can still appear in some circumstances, and cross-user text is restricted to privileged roles. Those controls reduce exposure but do not remove the need for data classification, purpose, and retention governance.

## Compliance / certification boundary

No PostgreSQL logging knob proves SOC 2, ISO/IEC 27001, PCI DSS, CSAP, privacy-law compliance, or any certification. NIST SP 800-53 is a risk-managed control catalog whose controls are selected and tailored to mission/business needs; it does not prescribe that applications persist all SQL text or fixed universal retention periods. Retention and audit scope are therefore deployment-governance decisions, not package constants.

## Test-first evidence

RED source `72f3e1c245c4a26d1778802bab0661973143fe04` added `tests/test_postgres_logging_privacy_contract.py`. CI run `31429883906` reproduced the exact initial defect: Python 3.12 reported two intended failures because `log_statement` was still `all` and the blanket audit/compliance prose was still present.

A second test-first refinement on `9014c1337486c29208757178aade3d70f2d132a8` added explicit opt-in requirements for `pg_stat_statements` and disabled per-statement duration logging before the corresponding configuration change. Subsequent source `52f7879d875eb86a58ab9f93142d324b2ecd31be` implements that narrower content-retention boundary.

RED source `0984c66e8d7a6ba713446860b575bf582bc74c41` then made the remaining live-activity assurance explicit. CI `31432404368` failed the intended contract because the doctoring did not yet name `pg_stat_activity` or its live query-text visibility. This document closes that documentation boundary without disabling the operationally useful activity collector. No predecessor or synthetic-merge result transfers to later heads; final acceptance requires fresh validation of the unchanged final source under current repository governance.

## Rollback and recovery

If the safer baseline prevents an operator from satisfying a documented, purpose-specific audit requirement, do **not** restore blanket logging in the package default. Instead, maintain a deployment-owned overlay that enables only the necessary event/content classes for the authorized scope, defines access/retention/deletion, and can be disabled independently. If accidental content logging is discovered, stop the content-bearing logging path, preserve only evidence required by the incident/legal process, rotate or revoke exposed credentials where relevant, and follow the deployment's deletion/backup-expiry procedure for unnecessary copies.

## APA 7 references

Joint Task Force. (2025). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5, Release 5.2.0). National Institute of Standards and Technology. https://csrc.nist.gov/projects/cprt/catalog

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Error reporting and logging*. https://www.postgresql.org/docs/16/runtime-config-logging.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: The cumulative statistics system*. https://www.postgresql.org/docs/16/monitoring-stats.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: pg_stat_statements—Track statistics of SQL planning and execution*. https://www.postgresql.org/docs/16/pgstatstatements.html
