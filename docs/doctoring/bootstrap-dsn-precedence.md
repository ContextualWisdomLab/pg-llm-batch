# Bootstrap source precedence

## Problem

`PG_LLM_BATCH_DSN` and `PG_LLM_BATCH_SECRET_KEY` are bootstrap transports used only when a caller omits the corresponding explicit value. The prior implementation selected both with Python boolean truthiness (`explicit or environment_value`). That conflated omission with explicit false-valued input and could silently transfer database-target or decryption authority to ambient process state.

For the required Postgres DSN, an explicitly empty or whitespace-only value must not be replaced by `PG_LLM_BATCH_DSN` or passed down to libpq defaults. Non-string explicit values must also fail at the package boundary rather than reaching unrelated lower-layer behavior. For the optional Fernet bootstrap key, an explicit empty string is a deliberate statement that no key was supplied for this invocation and must not inherit an ambient key.

## Contract

`resolve_dsn()` distinguishes source absence, source type, and source value:

- the environment is consulted only when the explicit argument is `None`;
- an explicit Postgres DSN must be an exact `str`;
- explicit and environment-selected DSNs must be non-empty after whitespace inspection;
- invalid explicit values fail with bounded `ConfigError` before environment fallback or libpq target selection; and
- valid nonblank DSNs are returned unchanged rather than normalized or rewritten.

`resolve_secret_key()` uses the same source-precedence rule while preserving its optional-value semantics:

- the environment is consulted only when the explicit argument is `None`;
- an explicitly supplied Fernet key must be an exact `str`;
- an explicit empty string remains the empty string and does not inherit `PG_LLM_BATCH_SECRET_KEY`; and
- when neither source provides a key, the result remains `None`.

This boundary does not make secret persistence, serialization, or transport safer by itself. It only prevents ambient bootstrap state from silently replacing explicitly supplied caller intent.

## Verification

`tests/test_bootstrap_source_precedence.py` proves the replacement behavior against the public bootstrap helpers. The regressions populate ambient environment values while passing explicit invalid values so a rejected caller value cannot be confused with ordinary omitted-input fallback. They also prove that an omitted whitespace-only DSN is rejected, a valid explicit DSN retains exact text, and an explicit empty secret key remains explicit.

The fail-first replacement head demonstrated that protected-main truthiness selected ambient values or admitted the wrong type before the production repair. The production repair then moved fallback behind an explicit `None` check and added exact-string and required-nonblank validation. Final acceptance still requires the repository's complete exact-head CI, security, coverage, package, provenance, and review policy on the unchanged final source.

## Compatibility and rollback

Constructor and CLI call shapes remain unchanged. Callers that intentionally depended on explicit empty/non-string values falling through to environment state must now omit the argument to request environment fallback. Valid explicit DSNs and keys retain their original string values.

Rollback is an ordinary Git revert of this bounded bootstrap change. Rolling back reintroduces ambiguous authority selection and should occur only with a documented compatibility requirement and a safer replacement contract.

## References

Python Software Foundation. (2026). *argparse — Parser for command-line options, arguments and subcommands*. Python 3.14 documentation. https://docs.python.org/3.14/library/argparse.html

Python Software Foundation. (2026). *os — Miscellaneous operating system interfaces*. Python 3.14 documentation. https://docs.python.org/3.14/library/os.html
