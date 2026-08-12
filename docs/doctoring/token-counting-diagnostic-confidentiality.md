# Token-counting diagnostic confidentiality

## Status and scope

This document records the token-counting diagnostic confidentiality boundary implemented on protected `main` through PR #150 and the permanent regression evidence carried by the current follow-up. The change is intentionally narrow: generic lower-layer PostgreSQL/Psycopg token-counting failure text no longer becomes a package-owned debug log record. Token counting remains PostgreSQL-only and still fails closed when `pg_tiktoken` cannot produce an authoritative count.

## Problem and root cause

`TokenCounter.count_tokens()` previously caught a generic database failure and logged the exception object with `%s`. That made the package logger a secondary copy of lower-layer diagnostic text.

That diagnostic text cannot be assumed content-free. PostgreSQL ErrorResponse includes an always-present primary human-readable message, PostgreSQL server error-reporting APIs may interpolate run-time values into that message, and Psycopg exposes PostgreSQL diagnostic fields on database exceptions. Rendering an arbitrary lower-layer exception therefore creates an avoidable confidentiality boundary even at DEBUG severity.

The bounded repair emits only the fixed package-owned message `PostgreSQL token counting failed` for the generic failure class. The regression uses a prompt/secret-like sentinel inside a synthetic lower-layer failure and proves that the sentinel does not enter the package log while the fixed category remains observable.

## Finite package-owned diagnostic category

The generic database-failure branch does not include:

- PostgreSQL/Psycopg exception messages or `repr()` output;
- dynamic exception class names;
- SQL or bind values;
- PostgreSQL DSNs;
- prompt or system-prompt content;
- model/provider-controlled text;
- credentials; or
- chained exception objects.

The existing `UndefinedFunction` branch remains a separate fixed warning, `pg_tiktoken extension/functions unavailable`, because extension/function availability is a package-owned operational distinction. The authority remains **no Python tokenizer fallback**: this control neither broadens retry behavior nor introduces a Python-side tokenizer path.

## Security and privacy boundary

This control prevents an unauthorized secondary copy in package-owned diagnostics; it does **not** mask or destroy purpose-bound prompt content used for authorized token counting. Prompt text still crosses the reviewed PostgreSQL token-counting boundary because the workload requires it. Deployment authorization, PostgreSQL transport security, database access control, retention, and privileged database diagnostics remain separate controls.

This change does not claim that every message produced by PostgreSQL, Psycopg, a deployment logger, or an embedding host is redacted. It limits what this package-owned generic token-counting logging path exports.

## Verification

The permanent regression proves that a generic lower-layer failure whose text contains a unique sensitive sentinel does not place that sentinel in `pg_llm_batch.token_counter` logs, that the fixed generic token-counting failure category remains observable, and that the public result still fails closed through the existing bounded `RuntimeError` under the no-Python-tokenizer-fallback contract. Repository CI additionally validates Python 3.10, 3.12, and 3.14, owned production statement/branch coverage, public docstrings, security, SAST, package, and container behavior on the exact source relation.

## Rollback and recovery

Rollback to arbitrary lower-layer exception rendering would reopen the diagnostic disclosure risk and must be treated as a privacy regression. If operators require richer failure details, add a separately reviewed, purpose-bound diagnostic interface with explicit data classification and authorization rather than restoring arbitrary exception rendering.

No persisted product state or migration is changed by this boundary. Recovery from an application failure remains unchanged: restore PostgreSQL/`pg_tiktoken` availability or correct runtime conditions and retry under the existing package contract.

## References — APA 7

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Error and notice message fields*. https://www.postgresql.org/docs/18/protocol-error-fields.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Reporting errors within the server*. https://www.postgresql.org/docs/18/error-message-reporting.html

Psycopg Team. (2026). *Psycopg 3 documentation: errors — Package exceptions*. https://www.psycopg.org/psycopg3/docs/api/errors.html

The references support the engineering rationale and are not certification claims.