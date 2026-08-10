# Token-counter buffer resource boundary

## Purpose

`TokenCounter` uses `buffer_percentage` to reduce the configured per-batch token ceiling before any request is assembled. Because that value changes a hard resource limit, it is configuration authority rather than a presentation hint and must be validated before PostgreSQL or `pg_tiktoken` work starts.

## Contract

`buffer_percentage` must be an **exact integer** from **0 through 50**, inclusive. Python booleans are rejected even though `bool` subclasses `int`; floating-point values, numeric strings, containers, and other coercible or non-numeric objects are rejected rather than converted implicitly. When the caller omits the argument, the same exact-integer/range validation applies to the value selected from the configuration store.

Validation happens **before PostgreSQL** extension setup or token-counting connection acquisition. Invalid configuration therefore fails with bounded `ValidationError` and cannot create a database session, attempt `CREATE EXTENSION`, or delegate type semantics to lower layers.

A value of 0 is a valid explicit choice and means no token-limit buffer. Values above 50 or below 0 are invalid rather than silently clamped. A valid integer is retained exactly and the effective limit remains:

```text
effective_limit = int(max_tokens_per_batch * (1 - buffer_percentage / 100))
```

## Verification

`tests/test_token_counter_buffer_boundary.py` exercises booleans, floats, strings, lists, and dictionaries with a PostgreSQL seam that raises if connection acquisition is attempted. The regression therefore proves both the type/range contract and its ordering before PostgreSQL I/O.

`tests/test_token_counter_buffer_documentation.py` keeps this operator contract and the CHANGELOG synchronized. The normal repository gate additionally proves the existing 100% production statement/branch coverage and public-docstring requirements.

## Recovery and rollback

If configuration fails this boundary, correct the stored or explicit value to an integer from 0 through 50 and retry. Do not coerce malformed configuration at the caller or relax the guard to restore a run: that would make resource authority depend on Python truthiness or conversion behavior.

The implementation can be reverted mechanically because no schema or persisted representation changes, but rollback would restore acceptance of booleans/floats and raw type failures for other values. Such a rollback therefore requires a separately reviewed compatibility reason rather than routine incident recovery.

## References

Python Software Foundation. (2026). *Built-in types — Boolean values*. Python 3.14 documentation. https://docs.python.org/3/library/stdtypes.html
