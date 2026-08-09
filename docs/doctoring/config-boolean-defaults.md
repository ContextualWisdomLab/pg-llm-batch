# Boolean configuration fallback

## Purpose

Configuration rows in `com_config` are persisted as text and converted back to the type declared by `DEFAULT_CONFIG_INDEX`. Boolean conversion is intentionally finite and non-coercive: accepted values are `true`, `1`, `yes`, and `on` for true, and `false`, `0`, `no`, and `off` for false, matched case-insensitively.

Any other persisted text is a **malformed boolean**. It must not be interpreted using Python's general truth-value rules because every non-empty string is true. Instead, the loader returns the setting's **declared default**. This is especially important for a **false-default** feature flag: corrupt or manually mistyped text cannot silently enable behavior that operators and code declared disabled by default.

## Runtime contract

- Known boolean spellings retain their existing values.
- A malformed boolean value returns the exact default recorded for that configuration key.
- A key with boolean type metadata but no declared item fails closed to `False`.
- Integer, floating-point, mapping, sequence, and untyped custom-value behavior is unchanged.
- The fallback does not make malformed data valid. Operators should correct the affected `com_config` row after diagnosis.
- No credential, provider response, prompt, tenant identifier, or configuration value is added to public telemetry by this change.

This behavior is deterministic across cache initialization, a cache miss, and `show_config()`, because all three paths use the same `_deserialize_value()` function.

## Operational diagnosis

When a configured boolean appears to have fallen back, inspect the relevant `com_config.config_key` and `config_value` through trusted database administration tooling. Compare the stored text with the accepted vocabulary above. Repair the row with the CLI or a parameterized database update; do not broaden the parser to accept arbitrary prose, whitespace-bearing variants, or Python truthiness.

A fallback to the declared default is safer than raising during process startup because the existing configuration contract already uses declared defaults for malformed integers, floating-point values, mappings, and sequences. It also preserves service availability while preventing malformed text from overriding the reviewed default direction.

## Verification

Deterministic tests prove that:

1. all established true and false spellings remain accepted;
2. a malformed value for a false-default key remains false;
3. the existing true-default key falls back to true;
4. unknown untyped configuration continues to round-trip as text; and
5. this doctoring and the changelog retain the non-coercive contract.

The full gate must continue to prove production statement and branch coverage, public docstrings, Python 3.10/3.12/3.14 compatibility, lint, lock freshness, packaging, container builds, SAST, and security checks.

## Rollback

There is no database migration or persistent format change. Code **rollback** is mechanically simple, but it restores the former behavior in which any non-empty malformed string becomes true. If compatibility concerns arise, retain the declared-default fallback and correct the affected `com_config` data rather than restoring general truth-value coercion.

## Reference

Python Software Foundation. (2026). *Truth value testing*. Python 3.14.6 documentation. https://docs.python.org/3/library/stdtypes.html#truth-value-testing
