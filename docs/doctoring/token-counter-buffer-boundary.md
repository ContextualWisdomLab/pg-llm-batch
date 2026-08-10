# Token-counter and accumulator resource boundaries

## Purpose

`TokenCounter` and `BatchAccumulator` turn configuration into hard token, record, byte, and file ceilings. Those values are resource authority, not presentation hints, so they must be validated without Python truthiness or implicit coercion before PostgreSQL work or JSONL accumulation begins.

## Token buffer contract

`buffer_percentage` must be an **exact integer** from **0 through 50**, inclusive. Python booleans are rejected even though `bool` subclasses `int`; floating-point values, numeric strings, containers, and other coercible or non-numeric objects are rejected rather than converted implicitly. When the caller omits the argument, the same exact-integer/range validation applies to the value selected from the configuration store.

Validation happens **before PostgreSQL** extension setup or token-counting connection acquisition. Invalid configuration therefore fails with bounded `ValidationError` and cannot create a database session, attempt `CREATE EXTENSION`, or delegate type semantics to lower layers.

A value of 0 is a valid explicit buffer choice and means no token-limit buffer. Values above 50 or below 0 are invalid rather than silently clamped. A valid integer is retained exactly and the effective limit remains:

```text
effective_limit = int(max_tokens_per_batch * (1 - buffer_percentage / 100))
```

## Configured TokenCounter resource ceilings

Every configured hard ceiling selected by `TokenCounter` is an **exact positive integer** before PostgreSQL extension setup or token-counting connection acquisition. This applies to `token_limits.per_batch`, `token_limits.per_request`, `azure_limits.max_records_per_file`, `azure_limits.max_bytes_per_file`, and `azure_limits.max_files_per_job`. Their runtime attributes are `token_limit`, `default_model_limit`, `azure_max_records_per_file`, `azure_max_bytes_per_file`, and `azure_max_files_per_job` respectively.

Booleans, zero, negative integers, floats, strings, lists, dictionaries, and other coercible values fail with bounded `ValidationError`. The package does not convert these values, defer validation to arithmetic, or acquire `pg_tiktoken`/PostgreSQL resources first. The built-in defaults satisfy the same rule.

This fail-closed boundary prevents malformed configuration from becoming resource authority for aggregate token work, per-request token expectations, provider-file record/byte limits, or provider-job file counts. It also prevents raw Python `TypeError` failures from replacing the package's stable validation contract.

## BatchAccumulator record and byte ceilings

`BatchAccumulator` treats `max_records` and `max_bytes` as independent hard ceilings. An explicit value wins over the corresponding counter-owned configured default only when it is an **exact positive integer**. Booleans, floats, strings, containers, negative values, and **explicit zero** fail with `ValidationError`; zero is not treated as “argument omitted” and must never silently select a larger default through `explicit or configured_default` truthiness.

When the caller omits either argument with `None`, the **configured default** selected from `azure_max_records_per_file` or `azure_max_bytes_per_file` is validated by the same exact-positive-integer rule. A malformed configured default therefore cannot become accumulator authority merely because it came from an already constructed counter object.

This boundary is applied when the accumulator is constructed, before any JSONL record is accumulated. Valid explicit limits retain their exact integer values. The existing per-record `byte_size` and token-limit checks remain unchanged.

## Verification

`tests/test_token_counter_buffer_boundary.py` exercises booleans, floats, strings, lists, and dictionaries with a PostgreSQL seam that raises if connection acquisition is attempted. The regression therefore proves both the buffer type/range contract and its ordering before PostgreSQL I/O.

`tests/test_token_counter_limit_config_boundary.py` parametrizes all five configured hard ceilings across booleans, zero, negative integers, floats, strings, lists, and dictionaries. Its forbidden-PostgreSQL seam proves every malformed ceiling fails before `pg_tiktoken` or PostgreSQL acquisition.

`tests/test_batch_accumulator_limit_boundary.py` proves that explicit `max_records` and `max_bytes` accept only exact positive integers, that explicit zero is rejected instead of selecting a default, that malformed configured defaults fail after selection, and that reviewed positive explicit ceilings override configured defaults exactly.

`tests/test_token_counter_buffer_documentation.py` and `tests/test_batch_accumulator_limit_documentation.py` keep these operator contracts and CHANGELOG synchronized. The normal repository gate additionally proves the existing 100% production statement/branch coverage and public-docstring requirements.

## Recovery and rollback

If `buffer_percentage` fails validation, correct the stored or explicit value to an integer from 0 through 50 and retry. If any configured `per_batch`, `per_request`, `max_records_per_file`, `max_bytes_per_file`, or `max_files_per_job` ceiling fails, repair it to an exact positive integer before retrying. If an accumulator ceiling fails, provide an exact positive integer or repair the configured default. Do not coerce malformed values, clamp them silently, or use truthiness fallback to restore a run: those remedies make resource authority depend on Python conversion behavior rather than an explicit contract.

No schema or persisted representation changes. A mechanical code revert is possible, but it would restore acceptance of malformed configured resource ceilings, coercible buffer values, or truthiness-based accumulator ceilings, including explicit zero silently becoming a configured default. Such rollback therefore requires a separately reviewed compatibility reason rather than routine incident recovery.

## References

Python Software Foundation. (2026). *Built-in types — Boolean values*. Python 3.14 documentation. https://docs.python.org/3/library/stdtypes.html
