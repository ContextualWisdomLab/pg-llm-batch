# CLI secret-input boundary

## Problem

`config set-secret` is an operator credential-ingestion boundary. A secret value
must not be supplied as a positional command-line argument because process
arguments are an observable invocation surface on common operating systems and
can also be retained by shell tooling. The secret-store encryption boundary does
not mitigate exposure that happens before the value reaches PostgreSQL.

## Contract

The command accepts only the secret key in process arguments:

```text
python -m pg_llm_batch config set-secret gateway_api_key.default
```

The value is acquired separately:

- when standard input is an interactive terminal, `getpass.getpass()` requests
  one value without echoing typed characters;
- when standard input is non-interactive, exactly one bounded logical line is
  read from standard input so an existing secret-management process can pipe a
  value without placing it in the `pg_llm_batch` process argument vector;
- one terminal LF or CRLF is removed from non-interactive input;
- empty, multiline, carriage-return-containing, and values longer than 65,536
  characters fail closed before `SecretStore` is constructed or written; and
- errors, success output, logs, and tests never include the supplied plaintext.

The non-interactive path intentionally does not define or require a particular
external secret manager. Deployment owners may connect their existing
credential source to standard input without changing the repository's secret
storage or bootstrap-key contract.

## Verification

`tests/test_cli_secret_input_security.py` proves that plaintext is rejected from
process arguments, TTY input uses the no-echo primitive rather than an ordinary
stdin read, piped input is bounded and single-line, common terminal line endings
are normalized, and unsafe shapes fail closed. `tests/test_bootstrap_cli.py`
keeps the existing CLI routing test while providing its fixture value through
stdin.

The development sequence is intentionally test-first. Exact-head CI
`31298176124` on RED head `e8b256992b34a8651ab5a2f0cef350d5fbde4b75`
failed the two initial secret-input contracts on Python 3.10, 3.12, and 3.14
because the old parser still accepted a positional secret and required it when
stdin-only invocation was attempted. No predecessor-head failure is counted as
post-fix evidence.

## References

MITRE. (2025). *CWE-214: Invocation of process using visible sensitive
information*. Common Weakness Enumeration.
https://cwe.mitre.org/data/definitions/214.html

Python Software Foundation. (2026). *getpass — Portable password input*.
Python 3.14 documentation.
https://docs.python.org/3/library/getpass.html
