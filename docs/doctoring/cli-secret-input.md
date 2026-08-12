# CLI secret-input boundary

## Problem

`config set-secret` is an operator credential-ingestion boundary. A secret value
must not be supplied as a positional command-line argument because process
arguments are an observable invocation surface on common operating systems and
can also be retained by shell tooling. The secret-store encryption boundary does
not mitigate exposure that happens before the value reaches PostgreSQL.

Rejecting the old positional form is not sufficient if the argument parser then
reflects the rejected value in an error diagnostic. Python `argparse` normally
prints invalid-argument diagnostics to standard error and includes unrecognized
argument values. A legacy invocation can therefore disclose the same credential
through captured stderr unless unknown values are redacted before the parser
terminates.

A second framing boundary is the meaning of “one logical line.” Treating only
LF and CR as line separators is incomplete: terminal and text protocols also use
vertical tab, form feed, ASCII file/group/record separators, Unicode Next Line,
Unicode Line Separator, and Unicode Paragraph Separator. Accepting any of those
inside a secret would let a value cross the one-line contract under one parser
while being split into multiple logical records by another downstream tool.

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
- exactly one **terminal LF/CRLF** framing sequence may be removed by the
  non-interactive reader;
- the resulting value must contain none of LF, CR, **vertical tab**, **form
  feed**, ASCII file/group/record separators, Unicode **Next Line** (U+0085),
  **U+2028** Line Separator, or **U+2029** Paragraph Separator;
- empty values and values longer than 65,536 characters fail closed before
  `SecretStore` is constructed or written;
- rejected unrecognized argv values are replaced with a fixed `<redacted>`
  placeholder before `argparse` emits its standard error diagnostic, while
  non-value parser diagnostics retain their ordinary behavior; and
- errors, success output, captured test output, and test/runtime logs never
  include a supplied runtime secret value.

Only terminal LF/CRLF is normalization performed by the stdin reader. Other
logical separators remain part of the candidate value until the validator
rejects them, so a caller cannot smuggle an alternate line boundary by relying
on normalization differences.

The non-interactive path intentionally does not define or require a particular
external secret manager. Deployment owners may connect their existing
credential source to standard input without changing the repository's secret
storage or bootstrap-key contract.

## Verification

`tests/test_cli_secret_input_security.py` proves that plaintext is rejected from
process arguments without being reflected through parser diagnostics, TTY input
uses the no-echo primitive rather than an ordinary stdin read, `GetPassWarning`
aborts before an echoed fallback can read plaintext, piped input is bounded and
single-line, common terminal line endings are normalized, and unsafe shapes fail
closed. `tests/test_bootstrap_cli.py` keeps the existing CLI routing test while
providing its fixture value through stdin.

`tests/test_cli_secret_unicode_line_boundaries.py` expands the one-line
regression to vertical tab, form feed, ASCII file/group/record separators,
Unicode Next Line, U+2028, and U+2029, both embedded and trailing. It also
requires the rejected runtime value to stay out of the exported `ConfigError`.
`tests/test_cli_secret_unicode_line_documentation.py` keeps those separator names
and the terminal LF/CRLF-only normalization contract in both this doctoring
record and CHANGELOG.

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
coverage/docstring/lint/package gate in CI run `31300511133`.

A third RCA exercised the rejected legacy positional form as a confidentiality
boundary rather than checking only exit status. RED source head
`20e7fb24c4ce50029fc02552f662fe9c92b1fad0` retained parser exit code 2 but CI
run `31301173291` failed the new regression because stderr contained the exact
rejected `visible-secret` value (`1 failed, 359 passed, 3 deselected` in the
observed Python 3.12 job). Production head
`67296879d02a48ac06defaf42536b4360b6fb9b2` uses a narrow
`ArgumentParser.error()` boundary that replaces only the value-bearing
`unrecognized arguments:` suffix with a fixed placeholder. CI run
`31301227713`, Security Scan `31301227710`, and SAST Semgrep `31301227739` all
completed successfully on that source head.

The logical-line-separator RED at `9cca9f1b5a4096da3148d02d68845204ee0a64dc`
failed all sixteen embedded/trailing alternate-separator regressions because the
old validator rejected only LF and CR. Production head
`bd342cc84d459662c97a5a0f4c9b4b1b271dc005` closes the full separator set.
Documentation RED `2c961d7a79e2eb6abfd3523cf27358ddfb580bd3`
then failed only the missing authoritative separator/framing language (`1 failed,
376 passed, 3 deselected` on the observed Python 3.12 job). These RED results are
development provenance rather than final acceptance.

These PR-triggered runs remain development evidence under the current
synthetic-merge checkout workflow; final acceptance still requires the
repository's exact-source-head gate after that workflow hardening reaches
protected main.

## References

MITRE. (2025). *CWE-214: Invocation of process using visible sensitive
information*. Common Weakness Enumeration.
https://cwe.mitre.org/data/definitions/214.html

Python Software Foundation. (2026). *argparse — Parser for command-line options,
arguments and subcommands*. Python 3.14 documentation.
https://docs.python.org/3.14/library/argparse.html

Python Software Foundation. (2026). *getpass — Portable password input*.
Python 3.14 documentation.
https://docs.python.org/3/library/getpass.html
