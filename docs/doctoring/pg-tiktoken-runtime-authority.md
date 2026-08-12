# pg_tiktoken runtime authority

## Status

This assurance record applies to the active implementation that separates PostgreSQL extension provisioning from ordinary token-count execution. It does not claim that the change is implemented on protected `main` until the corresponding pull request is integrated.

## Security and operability boundary

`pg_tiktoken` installation is a provisioning responsibility. Ordinary `TokenCounter` construction and token-count requests must not execute `CREATE EXTENSION`, run extension installation scripts, or require the application identity to hold extension-install authority.

The supported runtime path verifies the already-provisioned capability using read-only PostgreSQL catalog/function resolution. The package checks that `pg_tiktoken` is present in `pg_extension` and that both `tiktoken_count(text,text)` and `tiktoken_encode(text,text)` resolve through `to_regprocedure`. The probe does not commit a transaction and does not mutate database objects.

If the extension or required functions are unavailable, runtime token counting remains fail-closed. The package does not install the extension on demand and does not introduce a Python tokenizer fallback. Operators must repair provisioning through the reviewed database image, migration, or host-owned provisioning path and then retry the operation.

This boundary preserves standalone and embedded deployments: a standalone installation may provision `pg_tiktoken` through the repository PostgreSQL bootstrap, while an embedding host may provision the extension independently. In both cases, the runtime identity needs only the privileges required to verify and execute the already-installed functions, not installation authority.

## Confidentiality and diagnostics

Readiness and token-count failures use package-owned bounded diagnostics. Prompt content, provider content, credentials, PostgreSQL DSNs, SQL bind values, and arbitrary lower-layer exception text are not copied into package-owned token-count diagnostics. This is a diagnostic-copy control, not masking of content on its authorized token-counting data path.

## Recovery and rollback

When readiness fails, operators should verify that the intended database contains the reviewed `pg_tiktoken` installation and the expected function signatures, repair provisioning under an appropriately privileged administrative identity, and retry with the ordinary runtime role. Do not grant extension-install privileges to the runtime role merely to make request execution self-heal.

A product rollback must use the normal reviewed release rollback path. Reintroducing request-time `CREATE EXTENSION` is not an acceptable operational workaround because it restores elevated DDL authority to the request path.

## Verification evidence

The focused runtime-authority regression uses an inspectable Psycopg double and requires `TokenCounter` initialization to establish readiness without any `CREATE EXTENSION` statement or commit. Repository CI additionally exercises Python 3.10, 3.12, and 3.14, exact owned-production coverage and public docstrings, package construction, container/PostgreSQL smokes, security scanning, and release acceptance on the final exact source head.

## Primary references

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE EXTENSION*. https://www.postgresql.org/docs/18/sql-createextension.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_extension*. https://www.postgresql.org/docs/18/catalog-pg-extension.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_available_extensions*. https://www.postgresql.org/docs/18/view-pg-available-extensions.html
