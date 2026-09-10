# Bootstrap source precedence

## Problem

`PG_LLM_BATCH_DSN` and `PG_LLM_BATCH_SECRET_KEY` are bootstrap transports used only when a caller omits the corresponding explicit value. The prior implementation selected both with Python boolean truthiness (`explicit or environment_value`). That conflated omission with explicit false-valued input and could silently transfer database-target or decryption authority to ambient process state.

For the required Postgres DSN, an explicitly empty or whitespace-only value must not be replaced by `PG_LLM_BATCH_DSN` or passed down to libpq defaults. Non-string explicit values must also fail at the package boundary rather than reaching unrelated lower-layer behavior. For the Fernet bootstrap key, an explicit empty string is a deliberate statement that no key was supplied for this invocation and must not inherit an ambient key. The resolver may still return `None` or that empty string; `SecretStore` construction then fails closed. Omitting the key is not a supported unencrypted persistence mode.

A separate CLI confidentiality boundary applies before bootstrap resolution. PostgreSQL connection information can carry passwords, password-file locations, TLS private-key material, TLS key passwords, and OAuth client secrets. Accepting those values through `--dsn` copies credential material or credential-bearing locations into process invocation state, where operating-system process inspection and shell history can expose them. The CLI therefore needs to retain explicit database targeting without making credential-bearing conninfo a normal argv transport.

## Contract

`resolve_dsn()` distinguishes source absence, source type, and source value:

- the environment is consulted only when the explicit argument is `None`;
- an explicit Postgres DSN must be an exact `str`;
- explicit and environment-selected DSNs must be non-empty after whitespace inspection;
- invalid explicit values fail with bounded `ConfigError` before environment fallback or libpq target selection; and
- valid nonblank DSNs are returned unchanged rather than normalized or rewritten.

`resolve_secret_key()` uses the same source-precedence rule while preserving omitted-value resolution:

- the environment is consulted only when the explicit argument is `None`;
- an explicitly supplied Fernet key must be an exact `str`;
- an explicit empty string remains the empty string and does not inherit `PG_LLM_BATCH_SECRET_KEY`; and
- when neither source provides a key, the result remains `None`.

The standalone CLI adds a narrower transport rule for explicit `--dsn` values:

- parse the supplied value with Psycopg/libpq-compatible `conninfo_to_dict()` rather than ad-hoc URI or keyword matching;
- permit credential-free selectors such as password-free PostgreSQL URIs, keyword conninfo, and `service=` selectors;
- reject conninfo that explicitly contains `password`, `passfile`, `sslkey`, `sslpassword`, or `oauth_client_secret` before bootstrap resolution or database connection work;
- reject malformed conninfo with a fixed parser diagnostic that does not reproduce the rejected argv value; and
- preserve the exact accepted selector string so downstream source-precedence and libpq semantics remain unchanged.

The CLI restriction does not prohibit standard libpq authentication. Operators may keep password/private-key material outside argv using reviewed libpq mechanisms such as the default password file, `PGPASSFILE`, a connection service file, default or environment-selected TLS key material, or deployment-owned secret injection. `PG_LLM_BATCH_DSN` remains a bootstrap transport and is not claimed to be a universal secrets manager; deployments should select an appropriate secret mechanism for their threat model.

This boundary does not make secret persistence, serialization, transport, TLS, or server identity safe by itself. It prevents two specific authority/confidentiality failures: ambient bootstrap state silently replacing explicit caller intent, and credential-bearing explicit CLI conninfo becoming process-argument data.

## Verification

`tests/test_bootstrap_source_precedence.py` proves the replacement behavior against the public bootstrap helpers. The regressions populate ambient environment values while passing explicit invalid values so a rejected caller value cannot be confused with ordinary omitted-input fallback. They also prove that an omitted whitespace-only DSN is rejected, a valid explicit DSN retains exact text, and an explicit empty secret key remains explicit.

`tests/test_cli_dsn_argv_security.py` defines the CLI transport contract. It requires password-bearing PostgreSQL URIs, keyword `password=`, and explicit `passfile=` values to fail without reflecting a unique secret sentinel; it separately requires malformed conninfo to fail without reflection and confirms that credential-free URI, keyword, and service selectors retain exact text.

The fail-first bootstrap replacement head demonstrated that protected-main truthiness selected ambient values or admitted the wrong type before the production repair. The CLI fail-first branch independently demonstrated that protected main accepted credential-bearing `--dsn` values unchanged. The CLI production repair uses libpq-compatible parsing only to classify whether argv contains prohibited credential parameters; it does not rewrite accepted connection information or change bootstrap precedence. Final acceptance still requires the repository's complete exact-head Python 3.10/3.12/3.14, 100% owned production statement/branch coverage, public docstrings, package, security, SAST, required-workflow, review-thread, and live ruleset evidence on one unchanged final source.

## Compatibility and rollback

Bootstrap helper call shapes remain unchanged. Callers that intentionally depended on explicit empty/non-string values falling through to environment state must now omit the argument to request environment fallback. Valid explicit DSNs and keys retain their original string values.

The CLI keeps `--dsn` for explicit database selection but no longer accepts credentials or credential-file/private-key parameters in that process argument. Existing automation that embeds such material in `--dsn` must move authentication data to a standard libpq mechanism outside argv while preserving its database selector. This is an intentional confidentiality hardening, not silent credential removal.

Rollback is an ordinary Git revert of the bounded change. Rolling back the bootstrap rule reintroduces ambiguous authority selection; rolling back the CLI rule reintroduces credential-bearing process arguments. Either rollback should occur only with a documented compatibility requirement and a safer replacement contract.

## References

MITRE. (2026). *CWE-214: Invocation of process using visible sensitive information* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/214.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Database connection control functions*. https://www.postgresql.org/docs/18/libpq-connect.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: The password file*. https://www.postgresql.org/docs/18/libpq-pgpass.html

The Psycopg Team. (2026). *Psycopg 3 documentation: `conninfo` — manipulate connection strings*. https://www.psycopg.org/psycopg3/docs/api/conninfo.html

Python Software Foundation. (2026). *argparse — Parser for command-line options, arguments and subcommands*. Python 3.14 documentation. https://docs.python.org/3.14/library/argparse.html

Python Software Foundation. (2026). *os — Miscellaneous operating system interfaces*. Python 3.14 documentation. https://docs.python.org/3.14/library/os.html
