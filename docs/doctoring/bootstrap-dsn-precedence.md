# Bootstrap source precedence

## Problem

`PG_LLM_BATCH_DSN` and `PG_LLM_BATCH_SECRET_KEY` are bootstrap transports used only when a caller omits the corresponding explicit value. The prior implementation selected both with Python boolean truthiness (`explicit or environment_value`). That conflated omission with explicit false-valued input and could silently transfer database-target or decryption authority to ambient process state.

For the required Postgres DSN, an explicitly empty or whitespace-only value must not be replaced by `PG_LLM_BATCH_DSN` or passed down to driver defaults. Non-string explicit values must also fail at the package boundary rather than reaching unrelated lower-layer behavior. For the optional Fernet bootstrap key, an explicit empty string is a deliberate statement that no key was supplied for this invocation and must not inherit an ambient key.

A separate CLI confidentiality boundary applies before bootstrap resolution. PostgreSQL connection information can carry passwords, password-file locations, TLS private-key material, TLS key passwords, and OAuth client secrets. Accepting those values through `--dsn` copies credential material or credential-bearing locations into process invocation state, where operating-system process inspection and shell history can expose them. The CLI therefore needs to retain explicit database targeting without making credential-bearing conninfo a normal argv transport.

The production PostgreSQL client is selected behind `PostgresDriverPort`, but argv confidentiality is not a concrete-driver connectability decision. A driver may intentionally support only a bounded connection subset while operators still need to express a credential-free selector such as `service=` or `sslmode=` for another admitted deployment adapter. Using the current concrete driver's `parse_conninfo()` as the CLI security classifier therefore couples secret detection to backend compatibility and can reject safe selectors before the runtime owner has a chance to apply its own connection contract.

## Contract

`resolve_dsn()` distinguishes source absence, source type, and source value:

- the environment is consulted only when the explicit argument is `None`;
- an explicit Postgres DSN must be an exact `str`;
- explicit and environment-selected DSNs must be non-empty after whitespace inspection;
- invalid explicit values fail with bounded `ConfigError` before environment fallback or database target selection; and
- valid nonblank DSNs are returned unchanged rather than normalized or rewritten.

`resolve_secret_key()` uses the same source-precedence rule while preserving its optional-value semantics:

- the environment is consulted only when the explicit argument is `None`;
- an explicitly supplied Fernet key must be an exact `str`;
- an explicit empty string remains the empty string and does not inherit `PG_LLM_BATCH_SECRET_KEY`; and
- when neither source provides a key, the result remains `None`.

The standalone CLI adds a narrower transport rule for explicit `--dsn` values:

- classify PostgreSQL URI and libpq-style keyword parameter names at the CLI boundary without constructing a concrete PostgreSQL client;
- recognize URI user-info passwords and percent-decoded URI query parameter names, and recognize quoted, escaped, or whitespace-separated keyword assignments;
- permit credential-free selectors such as password-free PostgreSQL URIs, keyword conninfo, `service=` selectors, and options such as `sslmode=` even when the currently selected runtime adapter cannot connect with that selector;
- reject selectors that explicitly contain `password`, `passfile`, `sslkey`, `sslpassword`, or `oauth_client_secret` before bootstrap resolution or database connection work;
- reject malformed lexical selector forms with a fixed parser diagnostic that does not reproduce the rejected argv value; and
- preserve the exact accepted selector string so downstream source precedence and the selected runtime adapter retain connection-semantics authority.

The classifier is intentionally not a second PostgreSQL connection parser. Passing CLI admission proves only that the selector does not place a prohibited credential parameter in argv and that its outer URI/keyword framing is parseable. The admitted `PostgresDriverPort` remains responsible for deciding whether a credential-free selector is connectable, whether service resolution is configured, and which transport options are supported. Unsupported runtime semantics must still fail closed there rather than being approximated by the CLI.

The CLI restriction does not prohibit standard PostgreSQL authentication. Operators may keep password/private-key material outside argv using reviewed password files, service files, environment-selected deployment secrets, or another secret transport admitted by their concrete PostgreSQL adapter. `PG_LLM_BATCH_DSN` remains a bootstrap transport and is not claimed to be a universal secrets manager; deployments should select an appropriate secret mechanism for their threat model.

This boundary does not make secret persistence, serialization, transport, TLS, or server identity safe by itself. It prevents two specific authority/confidentiality failures: ambient bootstrap state silently replacing explicit caller intent, and credential-bearing explicit CLI conninfo becoming process-argument data.

## Verification

`tests/test_bootstrap_source_precedence.py` proves the replacement behavior against the public bootstrap helpers. The regressions populate ambient environment values while passing explicit invalid values so a rejected caller value cannot be confused with ordinary omitted-input fallback. They also prove that an omitted whitespace-only DSN is rejected, a valid explicit DSN retains exact text, and an explicit empty secret key remains explicit.

`tests/test_cli_dsn_argv_security.py` defines the CLI transport contract. It requires password-bearing PostgreSQL URIs, keyword `password=`, explicit credential-file/private-key parameters, percent-encoded sensitive URI query names, and case variants to fail without reflecting a unique secret sentinel. It separately requires malformed URI/keyword framing to fail without reflection and confirms that credential-free URI, keyword, service, quoted/escaped, whitespace-separated, and option-bearing selectors retain exact text. Those tests intentionally do not claim that every accepted selector is connectable by pg8000 or any other concrete adapter.

`tests/test_cli_postgres_driver_port.py` preserves the migration seam for explicitly injected driver doubles. When a caller supplies a `PostgresDriverPort` to `build_parser()` for adapter verification, that exact injected parser and invalid-conninfo classifier are still used. Production CLI construction, however, does not instantiate the runtime PostgreSQL client merely to classify argv confidentiality.

The fail-first bootstrap replacement head demonstrated that protected-main truthiness selected ambient values or admitted the wrong type before the production repair. The CLI fail-first branch independently demonstrated that protected main accepted credential-bearing `--dsn` values unchanged. During pg8000 production promotion, exact-head CI then demonstrated the opposite coupling failure: credential-free selectors accepted by the CLI contract were rejected because CLI admission delegated to pg8000's deliberately bounded connectability parser. The repair separates those authorities without weakening either one.

Final acceptance still requires the repository's complete exact-head supported-Python matrix, 100% owned production statement/branch coverage, public docstrings, package, security, SAST, required-workflow, review-thread, and live ruleset evidence on one unchanged final source.

## Compatibility and rollback

Bootstrap helper call shapes remain unchanged. Callers that intentionally depended on explicit empty/non-string values falling through to environment state must now omit the argument to request environment fallback. Valid explicit DSNs and keys retain their original string values.

The CLI keeps `--dsn` for explicit database selection but does not accept credentials or credential-file/private-key parameters in that process argument. Existing automation that embeds such material in `--dsn` must move authentication data to a reviewed PostgreSQL mechanism outside argv while preserving its database selector. This is an intentional confidentiality hardening, not silent credential removal.

Credential-free CLI selectors are no longer rejected solely because the currently selected runtime driver supports a smaller connection grammar. This does not expand that driver's runtime capabilities: a selector outside its admitted connection subset still fails at the driver boundary with that driver's bounded diagnostic. Deployments that require additional PostgreSQL selector semantics must admit them at the driver/ACL boundary rather than relying on CLI parsing as compatibility evidence.

Rollback is an ordinary Git revert of the bounded change. Rolling back the bootstrap rule reintroduces ambiguous authority selection; rolling back the CLI confidentiality rule reintroduces either credential-bearing process arguments or concrete-driver coupling at the argv boundary. Either rollback should occur only with a documented compatibility requirement and a safer replacement contract.

## References

MITRE. (2026). *CWE-214: Invocation of process using visible sensitive information* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/214.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Database connection control functions*. https://www.postgresql.org/docs/18/libpq-connect.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: The password file*. https://www.postgresql.org/docs/18/libpq-pgpass.html

Python Software Foundation. (2026). *argparse — Parser for command-line options, arguments and subcommands*. Python 3.14 documentation. https://docs.python.org/3.14/library/argparse.html

Python Software Foundation. (2026). *shlex — Simple lexical analysis*. Python 3.14 documentation. https://docs.python.org/3.14/library/shlex.html

Python Software Foundation. (2026). *urllib.parse — Parse URLs into components*. Python 3.14 documentation. https://docs.python.org/3.14/library/urllib.parse.html
