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
- if Python reports `GetPassWarning` because terminal echo cannot be disabled,
  the warning is promoted to a failure before `getpass` can fall back to visibly
  reading the secret; the command does not trade confidentiality for availability;
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
stdin read, `GetPassWarning` aborts before an echoed fallback can read plaintext,
piped input is bounded and single-line, common terminal line endings are
normalized, and unsafe shapes fail closed. `tests/test_bootstrap_cli.py` keeps
the existing CLI routing test while providing its fixture value through stdin.

The development sequence is intentionally test-first. PR CI run `31298176124`
was triggered from RED source head `e8b256992b34a8651ab5a2f0cef350d5fbde4b75`
but, under the current protected-main workflow, checked GitHub synthetic merge
commit `519ada6d67a01e66b877fc48d0b0ae5691a428d9`. It failed the two initial
secret-input contracts on Python 3.10, 3.12, and 3.14 because the old parser
still accepted a positional secret and required it when stdin-only invocation
was attempted. This is valid fail-first development evidence for the behavior,
but it is not exact-source-head acceptance evidence. No predecessor or
synthetic-merge-only result is counted as post-fix acceptance.

The echo-fallback regression was added separately at source head
`e88fe90246b5a97159af55ace5bbb62cb3525843`. CI run `31300391772` reached the
intended production boundary and failed because the implementation allowed a
`GetPassWarning` fallback. The implementation at
`44ffbe5298022652c497b3e1f0d28790839135e1` promoted that warning to a
fail-closed `ConfigError`; after correcting a case-sensitive diagnostic matcher
in the regression itself, source head `7be44e829a53946e382e5319f48a477fca15d193`
passed the Python 3.10, 3.12, and 3.14 unit-test jobs and the production
coverage/docstring/lint/package gate in CI run `31300511133`. These PR-triggered
runs remain development evidence under the current synthetic-merge checkout
workflow; final acceptance still requires the repository's exact-source-head
gate after that workflow hardening reaches protected main.

## References

MITRE. (2025). *CWE-214: Invocation of process using visible sensitive
information*. Common Weakness Enumeration.
https://cwe.mitre.org/data/definitions/214.html

Python Software Foundation. (2026). *getpass — Portable password input*.
Python 3.14 documentation.
https://docs.python.org/3/library/getpass.html
