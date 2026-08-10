# PostgreSQL logging privacy boundary

## Scope

`docker/postgres/postgresql.conf.custom` is an **optional operator-applied configuration surface**. The current container copies the file but does not automatically include it in the running PostgreSQL cluster. This doctoring therefore describes the safety contract for deployments that deliberately apply the file; it does not claim protected `main` currently enables these settings.

pg-llm-batch can process prompts, provider configuration, identifiers, lifecycle evidence, and secret-management operations. SQL statement text and bind values can therefore contain personal, confidential, or credential-bearing content. The package must preserve the business data itself for authorized batch work; the risk treatment is to avoid unnecessary secondary copies in logs/statistics rather than destructively masking production data.

## Root cause

The former example enabled `log_statement = 'all'`, slow/sample statement logging, transaction statement sampling, verbose error output, and `pg_stat_statements` collection/persistence, and described blanket SQL logging plus jurisdiction-specific multi-year retention as if they were generally required for compliance. PostgreSQL 16 explicitly warns that logged statements can reveal sensitive data and plaintext passwords, and extended-query protocol statement logging can include bind parameter values. PostgreSQL also documents that `pg_stat_statements` stores representative query text, with normalization caveats. The old example therefore made disclosure and retention a side effect of generic monitoring guidance rather than an explicit data-governance decision.

A separate operability inconsistency remained after the privacy repair: the example selected `csvlog` but did not enable `logging_collector`. PostgreSQL 16 explicitly requires the collector to generate CSV-format log output. An operator could therefore apply a configuration that advertised structured CSV logging and rotation without satisfying the server-start prerequisite that makes that destination effective.

A further privacy review found that the example still enabled `log_connections` and `log_disconnections` while claiming its operational log context excluded client addresses. PostgreSQL documents that connection log messages expose the client IP address when hostname lookup is disabled, and CSV log records have a fixed **client host:port** field. `log_hostname = off` prevents hostname resolution; it is not a client-network-metadata suppression control. The prior wording therefore understated persistent **client network metadata** and caused avoidable connection/disconnection event copies.

A reliability/performance review then found that the generic optional profile enabled both `track_io_timing` and `track_wal_io_timing` unconditionally. PostgreSQL documents that each setting repeatedly queries the operating system for the current time and can impose significant platform-dependent **timing overhead**, and specifically recommends `pg_test_timing` to measure that cost. A generic monitoring example should therefore not silently opt every deployment into timing instrumentation whose cost depends on the target host.

The same statistics review found `track_functions = all`. PostgreSQL's cumulative **statistics collection** has execution cost, and `track_functions` specifically collects call counts and elapsed execution time for procedural-language and SQL functions when enabled. The PostgreSQL default is `none`. Enabling **function statistics** across every deployment therefore creates avoidable instrumentation **overhead** without proving that the resulting data is needed for a concrete operational question.

A further transaction-metadata review found `track_commit_timestamp = on`. PostgreSQL documents this as a server-start option whose **default is off**, and its transaction-processing documentation states that enabling it records additional information in the `pg_commit_ts` directory for committed transactions. Commit-time metadata can be useful for specific replication/conflict or forensic questions, but collecting an additional persistent transaction record for every deployment without a defined consumer is not a neutral monitoring default.

## Decision

The reviewed baseline keeps ordinary SQL statement text and bind values out of server logs, makes query-text statistics collection opt-in, avoids connection-event logging unless a deployment has an explicit need, and keeps platform-dependent timing, function, and commit-timestamp instrumentation opt-in:

- `log_statement = none`;
- `log_min_duration_statement = -1` and `log_min_duration_sample = -1`;
- statement and transaction sample rates are `0`;
- `log_duration = off` to avoid high-volume per-statement events by default;
- `log_parameter_max_length = 0` and `log_parameter_max_length_on_error = 0`;
- `log_min_error_statement = PANIC` so ordinary errors do not add failing statement text;
- `log_error_verbosity = terse` so PostgreSQL omits `DETAIL`, `HINT`, `QUERY`, and `CONTEXT` error fields;
- `log_connections = off` and `log_disconnections = off` so connection lifecycle events are **opt-in** rather than an unconditional source of client-network records;
- `pg_stat_statements.track = none`, planning/utility tracking off, and `save = off` so preloading the module does not silently start representative-query retention if the extension is present;
- `track_io_timing = off` and `track_wal_io_timing = off` so platform-dependent timing overhead is not imposed until an operator has measured and accepted it;
- `track_functions = none` so function-call timing/count collection remains an **opt-in** diagnostic instead of package-default work; and
- `track_commit_timestamp = off` so additional per-transaction commit metadata is not written without a concrete purpose.

Checkpoint, lock-wait, temporary-file, autovacuum, query-ID, table/index, and activity-state telemetry remain available. I/O, WAL, function, and commit-timestamp evidence remain available as explicit opt-ins. This is not a claim that every remaining monitoring surface is content-free or cost-free: CSV client metadata, live activity tracking, and the remaining cumulative statistics have explicit residual boundaries.

This is **selective disclosure**, not blanket masking. The source data remains available to the authorized application/database path. If an embedding organization has a genuine requirement for content-bearing database audit logs, connection audit events, query-level `pg_stat_statements`, high-resolution I/O timing, function-call statistics, or commit timestamps, it must enable that separately under a purpose-specific authorization, least-privilege access model, retention/deletion schedule where data is persisted, encryption/storage boundary, access audit, legal basis where applicable, performance/storage budget, and incident procedure.

## CSV log routing and retention boundary

The optional example keeps `log_destination = 'csvlog'` for structured operational records and now sets `logging_collector = on`, because PostgreSQL requires the collector to generate CSV-format output. `logging_collector` is a **server start** parameter: applying the file therefore requires a restart/start boundary before the declared CSV destination becomes effective.

This change repairs **log routing** only. It does not widen the event/content classes permitted by the privacy settings above, and enabling the collector **does not define retention**. PostgreSQL's rotation knobs bound individual file age/size; they do not establish business retention, deletion, legal hold, backup expiry, residency, or external log-shipping policy. Those remain deployment-owned governance decisions. Operators should size and protect the collector's destination storage and keep file permissions/access aligned with the data classifications that remain in operational metadata.

If a deployment intentionally routes server logs to a platform-owned stderr/journald/logging pipeline instead of PostgreSQL-managed CSV files, it should use a deployment overlay that changes both destination and related collector/rotation settings coherently rather than leaving an ineffective `csvlog` declaration.

## Timing instrumentation overhead boundary

PostgreSQL documents `track_io_timing` and `track_wal_io_timing` as disabled by default because they repeatedly query the operating system for timing information and can cause significant overhead on some platforms. The safe generic profile therefore keeps both settings `off`.

A deployment that needs block/WAL timing must treat the feature as an **opt-in** performance decision. Measure the target host with PostgreSQL's `pg_test_timing`, evaluate the result under representative workload and concurrency, and enable only the timing classes whose diagnostic value justifies the measured runtime cost. The package does not assume that cloud, VM, bare-metal, or container clock-read costs are interchangeable, and a green functional test is not evidence that the timing overhead is acceptable for a production workload.

Disabling these two timing collectors does not disable ordinary database activity counters, query identifiers, activity-state visibility, checkpoint/lock/autovacuum events, or application-level telemetry. It only avoids imposing optional high-frequency clock reads before a deployment has established a performance budget.

## Function-statistics overhead boundary

PostgreSQL documents that cumulative **statistics collection** adds some execution overhead and that `track_functions` defaults to `none`. Setting it to `all` collects **function statistics** for procedural-language functions and SQL-language functions that PostgreSQL considers trackable, including call counts and execution time. That can be useful for targeted diagnosis, but it is not necessary for every pg-llm-batch deployment.

The generic profile therefore keeps `track_functions = none`. A deployment may **opt-in** to `pl` or `all` only when function-level attribution answers a concrete operational question. Before enabling it, measure representative workload and concurrency with the deployment's normal observability stack active, compare throughput/latency/CPU effects against the same workload with function tracking disabled, and record the accepted performance budget. Functional correctness alone is not evidence that instrumentation overhead is commercially acceptable.

This change does not disable `track_counts`, `track_activities`, query identifiers, checkpoint/lock/autovacuum logging, or application-level OpenTelemetry. If function statistics prove too expensive or are no longer needed, rollback is simply to restore `track_functions = none`; no business data migration is required.

## Commit-timestamp metadata boundary

PostgreSQL documents `track_commit_timestamp` as a boolean **server start** parameter whose **default is off**. When it is enabled, PostgreSQL records commit times and stores additional committed-transaction information in the `pg_commit_ts` directory. Those records support APIs such as `pg_xact_commit_timestamp()` and may be useful for specific replication-conflict or forensic workflows, but they are not required by pg-llm-batch's ordinary queue, lifecycle, readiness, or provider operations.

The generic profile therefore keeps `track_commit_timestamp = off`. A deployment may **opt-in** only when it has a concrete consumer for commit-time evidence and has accepted the extra transaction-metadata storage/write path plus the server-start change boundary. The decision should state which operator or replication procedure consumes the data, who may access it, and how the deployment handles restart/rollback. Enabling the setting is not a substitute for application audit events, durable checkpoint evidence, or release provenance.

Turning the option off again is a server-start configuration change; it does not erase or rewrite pg-llm-batch business tables. PostgreSQL also documents that commit timestamp information is eventually removed during vacuum, so this facility must not be treated as a package-owned durable audit-retention mechanism.

## Client-network metadata residual boundary

PostgreSQL's CSV schema contains a fixed **client host:port** column for emitted records from client backends. Consequently, even though the regular `log_line_prefix` does not include `%h` or `%r`, choosing `csvlog` can still persist client network metadata whenever another enabled event produces a backend log row. The package does not represent CSV output as network-identifier-free.

`log_connections` logs connection attempts plus successful authentication/authorization, and `log_disconnections` logs session termination with similar connection information. The optional baseline therefore leaves both `log_connections` and `log_disconnections` off. A deployment that needs connection-audit events may opt in, but must classify client IP/port as operational data and define a purpose, access boundary, retention/deletion policy, storage budget, and incident handling before doing so. Turning `log_hostname` off avoids reverse hostname lookup and additional hostname disclosure; it does **not** remove the client IP/port already carried by connection messages or the CSV field.

For environments where retaining the CSV client-address field on other operational events is unacceptable, use a deployment-owned logging destination/collector overlay whose emitted fields satisfy that deployment's data-minimization policy. That is an explicit operability/privacy tradeoff rather than a package-wide masking transformation.

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

RED source `0984c66e8d7a6ba713446860b575bf582bc74c41` then made the remaining live-activity assurance explicit. CI `31432404368` failed the intended contract because the doctoring did not yet name `pg_stat_activity` or its live query-text visibility. This document closes that documentation boundary without disabling the operationally useful activity collector.

RED source `4111a9fba56920046a0a9eb83ccce4ca87d8f418` added the CSV routing regression. CI `31434551317` failed on Python 3.14 with `KeyError: 'logging_collector'`, proving the optional file selected `csvlog` without its required collector. Production source `9e40e38ed071288341d8854fe678a181d7c3dc51` enables the collector. Documentation RED `dc168c154a23371d94739b84241c787e677cc94d` then failed CI `31434729307` because this doctoring had not yet explained the routing, restart, and retention boundary.

RED source `29bd3c5ff153ae75a503106104b522147b200ce2` added a connection-metadata minimization contract. CI `31435768146` failed on the intended first boundary because `log_connections` was still `on` (`1 failed, 355 passed, 3 deselected` on Python 3.14). Production source `ce09c5074d7d88f34ec58078a45743e890043f0e` disables both connection and disconnection event logging and corrects the configuration's client-address claim. This document records the remaining CSV `client host:port` field and the purpose-bound opt-in policy rather than falsely claiming the structured destination is network-metadata-free.

RED source `923f1ec87e5296efe96e9e4f1f5438ae99fabe2a` added the timing-overhead contract. CI `31436821943` failed exactly because `track_io_timing` remained `on` (`1 failed, 356 passed, 3 deselected` on Python 3.10); the same test also requires `track_wal_io_timing` to remain opt-in and this doctoring to bind the decision to `pg_test_timing`. Production source `88133a4755fcd7599331958e8ea269cce6dd83a6` turns both timing collectors off in the generic profile. This document closes the documented feasibility/measurement boundary without removing the metrics from deployments that explicitly accept their measured cost.

RED source `64fed077663877d939a86b9641bbb5960ddb3823` added the function-statistics contract. CI `31437980674` failed exactly because `track_functions` remained `all` (`1 failed, 357 passed, 3 deselected` on Python 3.10). Production source `ee555f69ab08a1eb000ed546945e29a7e34312ab` restores PostgreSQL's generic `none` boundary. This document adds the purpose/measurement/rollback contract so an operator can still opt in to function-call statistics after accepting representative-workload overhead rather than receiving it silently.

RED source `755487e1830fb7defc64626b3f5d6b301c1aa2f1` adds the commit-timestamp contract before the configuration repair. At that source, the new regression is deterministically RED because the optional profile still sets `track_commit_timestamp = on`. Production source `54476a262b354a88065b0c30d9188e0002b2846c` restores PostgreSQL's documented default-off boundary. This doctoring closes the explicit purpose, `pg_commit_ts`, server-start, rollback, and non-audit-retention semantics without removing commit timestamps from deployments that deliberately require them.

No predecessor or synthetic-merge result transfers to later heads; final acceptance requires fresh validation of the unchanged final source under current repository governance.

## Rollback and recovery

If the safer baseline prevents an operator from satisfying a documented, purpose-specific audit requirement, do **not** restore blanket logging in the package default. Instead, maintain a deployment-owned overlay that enables only the necessary event/content classes for the authorized scope, defines access/retention/deletion, and can be disabled independently. If accidental content or unnecessary client-network logging is discovered, stop the relevant logging path, preserve only evidence required by the incident/legal process, rotate or revoke exposed credentials where relevant, and follow the deployment's deletion/backup-expiry procedure for unnecessary copies.

If PostgreSQL-managed CSV collection is operationally unsuitable, use a deployment-owned overlay to select the intended logging destination and disable/adjust `logging_collector` coherently. If timing telemetry imposes unacceptable overhead, disable `track_io_timing` and `track_wal_io_timing` and re-establish a measurement baseline before any narrower re-enable. If function statistics impose unacceptable overhead or no longer have a reviewed diagnostic purpose, restore `track_functions = none`. If commit timestamps are no longer needed, restore `track_commit_timestamp = off` and restart under the deployment's change procedure. Rollback must not silently restore broad SQL/bind logging, unconditional connection event logging, fixed retention claims, or unmeasured/unneeded instrumentation.

## APA 7 references

Joint Task Force. (2025). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5, Release 5.2.0). National Institute of Standards and Technology. https://csrc.nist.gov/projects/cprt/catalog

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Error reporting and logging*. https://www.postgresql.org/docs/16/runtime-config-logging.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Run-time statistics*. https://www.postgresql.org/docs/16/runtime-config-statistics.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: The cumulative statistics system*. https://www.postgresql.org/docs/16/monitoring-stats.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Replication*. https://www.postgresql.org/docs/16/runtime-config-replication.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Transactions and identifiers*. https://www.postgresql.org/docs/16/transaction-id.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: pg_stat_statements—Track statistics of SQL planning and execution*. https://www.postgresql.org/docs/16/pgstatstatements.html
