# Token-counting diagnostic confidentiality

## Status and scope

This document records the ACTIVE-PR #87 repair for Issue #131. It is staged branch behavior until protected integration. The change is intentionally narrow: generic lower-layer PostgreSQL/Psycopg token-counting failure text no longer becomes a package-owned debug log record. Token counting remains PostgreSQL-only and still fails closed when `pg_tiktoken` cannot produce an authoritative count.

## Problem and root cause

`TokenCounter.count_tokens()` previously caught a generic database failure and logged the exception object with `%s`. That made the package logger a secondary copy of lower-layer diagnostic text.

The old source comment treated this as a false positive because the application did not deliberately pass a credential to the logger. That assumption was not enforceable. PostgreSQL ErrorResponse includes an always-present primary human-readable message, and PostgreSQL server error-reporting APIs may interpolate run-time values into that primary message. Psycopg exposes PostgreSQL diagnostic fields, including the primary message, on database exceptions. Rendering an arbitrary lower-layer exception therefore cannot be treated as content-free merely because logging is at DEBUG severity.

A realistic RED regression used a prompt/secret-like sentinel inside a synthetic lower-layer failure and proved the old debug record copied the sentinel verbatim. The correction removes exception rendering entirely from this generic branch and emits only the fixed message `PostgreSQL token counting failed`.

## Finite package-owned diagnostic category

The generic database-failure branch now emits a **finite package-owned diagnostic category** rather than lower-layer exception text. It does not include:

- PostgreSQL/Psycopg exception messages or `repr()` output;
- dynamic exception class names;
- SQL or bind values;
- PostgreSQL DSNs;
- prompt or system-prompt content;
- model/provider-controlled text;
- credentials; or
- chained exception objects.

The existing `UndefinedFunction` branch remains a separate fixed warning, `pg_tiktoken extension/functions unavailable`, because extension/function availability is a package-owned operational distinction. The authority remains **no Python tokenizer fallback**: this repair neither broadens retry behavior nor introduces a Python-side tokenizer path.

## Security and privacy boundary

This control prevents an unauthorized secondary copy in package-owned diagnostics; it does **not** mask or destroy purpose-bound prompt content used for authorized token counting. Prompt text still crosses the reviewed PostgreSQL token-counting boundary because the workload requires it. Deployment authorization, PostgreSQL transport security, database access control, retention, and privileged database diagnostics remain separate controls.

This change does not claim that every message produced by PostgreSQL, Psycopg, a deployment logger, or an embedding host is redacted. It limits what this package-owned generic token-counting logging path exports.

## Verification

The permanent regression must prove all of the following:

1. a generic lower-layer failure whose text contains a unique sensitive sentinel does not place that sentinel in `pg_llm_batch.token_counter` logs;
2. the fixed generic token-counting failure category remains observable;
3. the public result still fails closed through the existing bounded `RuntimeError` under the **no Python tokenizer fallback** contract;
4. the separate `UndefinedFunction` availability behavior remains unchanged; and
5. Python 3.10, 3.12, and 3.14 plus owned production statement/branch coverage, public docstrings, security, SAST, package, and container gates remain green on the final source relation.

## Rollback and recovery

**Rollback** restores the previous source revision only if a regression requires it, but doing so reopens the lower-layer diagnostic disclosure risk and must be treated as a privacy regression rather than a harmless logging change. If operators need richer failure details, add a separately reviewed, purpose-bound diagnostic interface with explicit data classification and authorization instead of restoring arbitrary exception rendering.

No persisted product state or migration is changed by this repair. Recovery from the application failure remains the same as before: correct PostgreSQL/`pg_tiktoken` availability or input/runtime conditions and retry the caller operation under the existing package contract.

## References — APA 7

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Error and notice message fields*. https://www.postgresql.org/docs/18/protocol-error-fields.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Reporting errors within the server*. https://www.postgresql.org/docs/18/error-message-reporting.html

Psycopg Team. (2026). *Psycopg 3 documentation: errors — Package exceptions*. https://www.psycopg.org/psycopg3/docs/api/errors.html

This reference list follows **APA 7** conventions for group authors and web documentation. References support the engineering rationale and are not certification claims.