# Bootstrap DSN precedence

## Problem

`PG_LLM_BATCH_DSN` is a bootstrap transport used only when a caller does not
supply an explicit PostgreSQL target. The previous implementation selected the
DSN with Python boolean truthiness:

```text
explicit or PG_LLM_BATCH_DSN
```

That expression treats an omitted value (`None`) and an explicitly supplied
empty string as equivalent. When the environment contains a valid DSN, a caller
that explicitly supplies an empty DSN can therefore be redirected silently to
the environment-selected database instead of receiving an input error. At an
operator boundary, fallback must not replace an explicit but invalid target.

## Contract

`resolve_dsn()` distinguishes source absence from source value:

- a non-empty explicit DSN wins over the environment;
- an explicitly supplied empty string fails closed with `ConfigError` and does
  not consult `PG_LLM_BATCH_DSN`;
- the environment is consulted only when the explicit argument is omitted
  (`None`);
- a missing or empty environment DSN still fails with the existing bootstrap
  configuration error; and
- optional Fernet bootstrap-key resolution is unchanged by this slice.

The distinction matches Python's command-line model: an optional argument may be
absent and receive a default, while a supplied argument is an explicit input.
`os.environ` remains the process-environment mapping used only by the omitted
DSN path.

## Verification

`tests/test_bootstrap_explicit_dsn_precedence.py` proves the regression directly:
with a valid `PG_LLM_BATCH_DSN` present, `resolve_dsn("")` must raise rather than
select the environment target. Existing bootstrap tests continue to prove that a
non-empty explicit DSN wins, an omitted argument uses the environment, and an
omitted argument without environment configuration fails.

RED source head `aea84e1d27822826ae22b7d532d87ede0025e5a7` reached the intended production
boundary in CI run `31305290555`, Python 3.12 job `93224552797`: the new test
failed with `DID NOT RAISE ConfigError` while the old truthiness expression
silently selected `postgresql://environment`. This is fail-first development
evidence; it is not final acceptance evidence.

The repair at source head `a0aa1ec7281aeb12ecbb732139742bd12d004286`
consults the environment only when `explicit is None` and rejects an explicitly
empty value before environment lookup. Final acceptance still requires the full
repository CI/security/review evidence on the final unchanged source head under
the repository's exact-source evidence policy.

## Rollback

Rollback is the ordinary Git revert of this bounded bootstrap change. Rolling
back restores the unsafe ambiguity between omitted and explicitly empty DSN
inputs, so rollback is appropriate only if a documented compatibility contract
requires that ambiguity and a safer explicit migration is provided.

## References

Python Software Foundation. (2026). *argparse — Parser for command-line options,
arguments and subcommands*. Python 3.14.6 documentation. Retrieved August 9,
2026, from https://docs.python.org/3.14/library/argparse.html

Python Software Foundation. (2026). *os — Miscellaneous operating system
interfaces*. Python 3.14.6 documentation. Retrieved August 9, 2026, from
https://docs.python.org/3.14/library/os.html
