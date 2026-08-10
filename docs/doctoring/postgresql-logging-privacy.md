# PostgreSQL logging privacy boundary

## Scope

`docker/postgres/postgresql.conf.custom` is an **optional operator-applied configuration surface**. The current container copies the file but does not automatically include it in the running PostgreSQL cluster. This doctoring therefore describes the safety contract for deployments that deliberately apply the file; it does not claim protected `main` currently enables these settings.

pg-llm-batch can process prompts, provider configuration, identifiers, lifecycle evidence, and secret-management operations. SQL statement text and bind values can therefore contain personal, confidential, or credential-bearing content. The package must preserve the business data itself for authorized batch work; the risk treatment is to avoid unnecessary secondary copies in server logs rather than destructively masking production data.

## Root cause

The former example enabled `log_statement = 'all'`, slow/sample statement logging, transaction statement sampling, and verbose error output, and described blanket SQL logging plus jurisdiction-specific multi-year retention as if they were generally required for compliance. PostgreSQL 16 explicitly warns that logged statements can reveal sensitive data and plaintext passwords, and extended-query protocol statement logging can include bind parameter values. That configuration made disclosure and retention a side effect of generic monitoring guidance rather than an explicit data-governance decision.

## Decision

The reviewed baseline keeps ordinary SQL statement text and bind values out of server logs:

- `log_statement = none`;
- `log_min_duration_statement = -1` and `log_min_duration_sample = -1`;
- statement and transaction sample rates are `0`;
- `log_parameter_max_length = 0` and `log_parameter_max_length_on_error = 0`;
- `log_min_error_statement = PANIC` so ordinary errors do not add failing statement text;
- `log_error_verbosity = terse` so PostgreSQL omits `DETAIL`, `HINT`, `QUERY`, and `CONTEXT` error fields; and
- `log_duration = on` retains duration evidence without forcing query-text logging.

Connection, disconnection, checkpoint, lock-wait, temporary-file, autovacuum, I/O, WAL, function, commit-timestamp, and query-ID telemetry remain available because these signals can answer many operational questions without retaining prompt or secret content.

This is **selective disclosure**, not blanket masking. The source data remains available to the authorized application/database path. If an embedding organization has a genuine requirement for content-bearing database audit logs, it must enable that separately under a purpose-specific authorization, least-privilege access model, retention/deletion schedule, encryption/storage boundary, access audit, legal basis, and incident procedure.

## pg_stat_statements residual boundary

The optional file still preloads `pg_stat_statements` and configures it for top-level statistics, but the protected-main initialization script does not create that extension. If a deployment creates it, PostgreSQL can retain representative query text and the documentation notes that constants are usually normalized but may appear in some circumstances. Access to cross-user SQL text is privileged, yet privilege is not a substitute for data classification and retention governance. Operators that do not need query text should not enable the extension merely to obtain an audit trail.

## Compliance / certification boundary

No PostgreSQL logging knob proves SOC 2, ISO/IEC 27001, PCI DSS, CSAP, privacy-law compliance, or any certification. NIST SP 800-53 is a risk-managed control catalog whose controls are selected and tailored to mission/business needs; it does not prescribe that applications persist all SQL text or fixed universal retention periods. Retention and audit scope are therefore deployment-governance decisions, not package constants.

## Test-first evidence

RED source `72f3e1c245c4a26d1778802bab0661973143fe04` added `tests/test_postgres_logging_privacy_contract.py`. CI run `31429883906` reproduced the exact defect: Python 3.12 reported two intended failures because `log_statement` was still `all` and the blanket audit/compliance prose was still present. The production configuration was then changed on the same branch; no protected-main or predecessor check is treated as GREEN evidence for that later head.

## Rollback and recovery

If the safer baseline prevents an operator from satisfying a documented, purpose-specific audit requirement, do **not** restore blanket logging in the package default. Instead, maintain a deployment-owned overlay that enables only the necessary event/content classes for the authorized scope, defines access/retention/deletion, and can be disabled independently. If accidental content logging is discovered, stop the content-bearing logging path, preserve only evidence required by the incident/legal process, rotate or revoke exposed credentials where relevant, and follow the deployment's deletion/backup-expiry procedure for unnecessary copies.

## APA 7 references

Joint Task Force. (2025). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5, Release 5.2.0). National Institute of Standards and Technology. https://csrc.nist.gov/projects/cprt/catalog

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: Error reporting and logging*. https://www.postgresql.org/docs/16/runtime-config-logging.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: pg_stat_statements—Track statistics of SQL planning and execution*. https://www.postgresql.org/docs/16/pgstatstatements.html
