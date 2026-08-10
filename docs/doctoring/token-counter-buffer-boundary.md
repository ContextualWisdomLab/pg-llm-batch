# Token-counter and accumulator resource boundaries

## Purpose

`TokenCounter` and `BatchAccumulator` turn configuration into hard token, record, and byte ceilings. Those values are resource authority, not presentation hints, so they must be validated without Python truthiness or implicit coercion before PostgreSQL work or JSONL accumulation begins.

## Token buffer contract

`buffer_percentage` must be an **exact integer** from **0 through 50**, inclusive. Python booleans are rejected even though `bool` subclasses `int`; floating-point values, numeric strings, containers, and other coercible or non-numeric objects are rejected rather than converted implicitly. When the caller omits the argument, the same exact-integer/range validation applies to the value selected from the configuration store.

Validation happens **before PostgreSQL** extension setup or token-counting connection acquisition. Invalid configuration therefore fails with bounded `ValidationError` and cannot create a database session, attempt `CREATE EXTENSION`, or delegate type semantics to lower layers.

A value of 0 is a valid explicit buffer choice and means no token-limit buffer. Values above 50 or below 0 are invalid rather than silently clamped. A valid integer is retained exactly and the effective limit remains:

```text
effective_limit = int(max_tokens_per_batch * (1 - buffer_percentage / 100))
```

## BatchAccumulator record and byte ceilings

`BatchAccumulator` treats `max_records` and `max_bytes` as independent hard ceilings. An explicit value wins over the corresponding counter-owned configured default only when it is an **exact positive integer**. Booleans, floats, strings, containers, negative values, and **explicit zero** fail with `ValidationError`; zero is not treated as “argument omitted” and must never silently select a larger default through `explicit or configured_default` truthiness.

When the caller omits either argument with `None`, the **configured default** selected from `azure_max_records_per_file` or `azure_max_bytes_per_file` is validated by the same exact-positive-integer rule. A malformed configured default therefore cannot become accumulator authority merely because it came from an already constructed counter object.

This boundary is applied when the accumulator is constructed, before any JSONL record is accumulated. Valid explicit limits retain their exact integer values. The existing per-record `byte_size` and token-limit checks remain unchanged.

## Verification

`tests/test_token_counter_buffer_boundary.py` exercises booleans, floats, strings, lists, and dictionaries with a PostgreSQL seam that raises if connection acquisition is attempted. The regression therefore proves both the buffer type/range contract and its ordering before PostgreSQL I/O.

`tests/test_batch_accumulator_limit_boundary.py` proves that explicit `max_records` and `max_bytes` accept only exact positive integers, that explicit zero is rejected instead of selecting a default, that malformed configured defaults fail after selection, and that reviewed positive explicit ceilings override configured defaults exactly.

`tests/test_token_counter_buffer_documentation.py` and `tests/test_batch_accumulator_limit_documentation.py` keep these operator contracts and CHANGELOG synchronized. The normal repository gate additionally proves the existing 100% production statement/branch coverage and public-docstring requirements.

## Recovery and rollback

If `buffer_percentage` fails validation, correct the stored or explicit value to an integer from 0 through 50 and retry. If an accumulator ceiling fails, provide an exact positive integer or repair the configured default. Do not coerce malformed values, clamp them silently, or use truthiness fallback to restore a run: those remedies make resource authority depend on Python conversion behavior rather than an explicit contract.

No schema or persisted representation changes. A mechanical code revert is possible, but it would restore acceptance of coercible buffer values and truthiness-based accumulator ceilings, including explicit zero silently becoming a configured default. Such rollback therefore requires a separately reviewed compatibility reason rather than routine incident recovery.

## References

Python Software Foundation. (2026). *Built-in types — Boolean values*. Python 3.14 documentation. https://docs.python.org/3/library/stdtypes.html
