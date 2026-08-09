# Bootstrap source precedence

## Problem

`PG_LLM_BATCH_DSN` and `PG_LLM_BATCH_SECRET_KEY` are bootstrap transports used
only when a caller does not supply the corresponding explicit value. The
previous implementation selected both values with Python boolean truthiness:

```text
explicit or bootstrap_environment_value
```

That expression treats an omitted value (`None`) and an explicitly supplied
empty string as equivalent. For the required DSN, a caller that explicitly
supplies an empty target can be redirected silently to the environment-selected
database instead of receiving an input error. A whitespace-only explicit DSN is
also unsafe even though it is truthy: passing it through to libpq delegates
connection-target selection to lower-level defaults instead of preserving a
reviewable explicit database target. For the optional Fernet key, an explicit
empty value can silently inherit an ambient bootstrap key and therefore select a
different decryption authority than the caller requested. At an operator
boundary, fallback must not replace explicit input merely because that input is
false-valued, and a required explicit database target must contain non-whitespace
content.

## Contract

`resolve_dsn()` distinguishes source absence from source value:

- a nonblank explicit DSN wins over the environment and is retained byte-for-byte;
- an explicitly supplied empty or whitespace-only string fails closed with
  `ConfigError` and does not consult `PG_LLM_BATCH_DSN` or reach libpq;
- the environment is consulted only when the explicit argument is omitted
  (`None`); and
- a missing or empty environment DSN still fails with the existing bootstrap
  configuration error.

`resolve_secret_key()` applies the same source-precedence rule while retaining
its optional-value semantics:

- a non-empty explicit key wins over the environment;
- an **explicit empty Fernet** bootstrap key is preserved as the empty string
  and never replaced by an **ambient bootstrap key**;
- `PG_LLM_BATCH_SECRET_KEY` is consulted only when the explicit argument is
  omitted (`None`); and
- when neither source provides a key, the result remains `None`.

An explicit empty key does not make encrypted records decryptable. It expresses
that this invocation has no Fernet key and prevents an ambient process value
from silently changing the selected decryption authority. `SecretStore` retains
its existing behavior for missing or empty keys, and an encrypted record still
fails closed when no usable key is configured.

The distinction matches Python's command-line model: an optional argument may be
absent and receive a default, while a supplied argument is explicit input.
`os.environ` remains the process-environment mapping used only by omitted
bootstrap-value paths.

## Verification

`tests/test_bootstrap_explicit_dsn_precedence.py` proves the required-DSN
regressions directly: with a valid `PG_LLM_BATCH_DSN` present,
`resolve_dsn("")` and whitespace-only explicit values must raise rather than
select the environment target or delegate target selection to libpq defaults.
`tests/test_bootstrap_cli.py` proves the optional-key counterpart: with an
ambient `PG_LLM_BATCH_SECRET_KEY` present, `resolve_secret_key("")` returns the
explicit empty string rather than the ambient key.

Existing bootstrap tests continue to prove that nonblank explicit values win
without normalization, omitted arguments use their environment values, an
omitted DSN without environment configuration fails, and an omitted optional
key without environment configuration returns `None`.

The DSN RED source head `aea84e1d27822826ae22b7d532d87ede0025e5a7`
reached the intended production boundary in CI run `31305290555`, Python 3.12
job `93224552797`: the new test failed with `DID NOT RAISE ConfigError` while
the old truthiness expression silently selected `postgresql://environment`.
The explicit-key RED source head `683dd533052d8b6f2aef0147ca3260760f11b1f6`
proved the same truthiness defect for the optional key: an explicit empty string
returned `environment-key` instead. A later fail-first regression at source head
`4f427f4577fc5a3c6498d3ace1c78d70f59b8f8e` extended the required-DSN contract
to whitespace-only explicit values before the production guard recognized
those inputs. These are fail-first development evidence, not final acceptance
evidence.

The DSN repair consults the environment only when `explicit is None` and rejects
an explicitly empty or whitespace-only required value before environment lookup
or libpq access. Nonblank explicit DSNs are returned unchanged; the guard does
not trim, rewrite, or otherwise normalize valid connection strings. The
optional-key repair likewise consults the environment only when `explicit is
None`, but preserves any explicitly supplied string because an empty optional
key is a valid statement of absence rather than an invalid database target.
Final acceptance still requires the full repository CI, security, and review
evidence on the final unchanged source head under the exact-source evidence
policy.

## Rollback

Rollback is the ordinary Git revert of this bounded bootstrap change. Rolling
back restores the unsafe ambiguity between omitted and explicitly empty inputs
and permits whitespace-only explicit DSNs to reach lower-level connection
defaults: required DSNs can silently retarget a command or lose an explicit
reviewable target, and optional Fernet key selection can silently inherit an
ambient decryption authority. A rollback is appropriate only if a documented
compatibility contract requires that ambiguity and a safer explicit migration
is provided.

## References

Python Software Foundation. (2026). *argparse — Parser for command-line options,
arguments and subcommands*. Python 3.14.6 documentation. Retrieved August 9,
2026, from https://docs.python.org/3.14/library/argparse.html

Python Software Foundation. (2026). *os — Miscellaneous operating system
interfaces*. Python 3.14.6 documentation. Retrieved August 9, 2026, from
https://docs.python.org/3.14/library/os.html
