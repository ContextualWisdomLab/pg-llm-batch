# Boolean configuration fallback and canonical writes

## Purpose

Configuration rows in `com_config` are persisted as text and converted back to the type declared by `DEFAULT_CONFIG_INDEX`. Boolean conversion is intentionally finite and non-coercive: accepted values are `true`, `1`, `yes`, and `on` for true, and `false`, `0`, `no`, and `off` for false, matched case-insensitively.

Any other persisted text is a **malformed boolean**. It must not be interpreted using Python's general truth-value rules because every non-empty string is true. Instead, the loader returns the setting's **declared default**. This is especially important for a **false-default** feature flag: corrupt or manually mistyped text cannot silently enable behavior that operators and code declared disabled by default.

## Runtime contract

- Known boolean spellings retain their existing values.
- A malformed boolean value returns the exact default recorded for that configuration key.
- A key with boolean type metadata but no declared item fails closed to `False`.
- Integer, floating-point, mapping, sequence, and untyped custom-value read behavior remains deterministic.
- The fallback does not make malformed external data valid. Operators should correct an affected legacy `com_config` row after diagnosis.
- No credential, provider response, prompt, tenant identifier, or configuration value is added to public telemetry by this change.

This behavior is deterministic across cache initialization, a cache miss, and `show_config()`, because all three paths use the same `_deserialize_value()` function.

## Canonical write and cache contract

`PostgresConfigStore.set()` applies the same type contract before it updates either PostgreSQL or the in-memory cache. It serializes the caller's value, deserializes that text through the declared configuration type, and then persists the **canonical** serialized result. The normalized value—not the caller's untyped object—is stored in the cache.

This gives one **read-after-write** result across process boundaries:

- CLI text such as `false` is cached immediately as the boolean `False` and is still `False` after a **cache reload**;
- numeric CLI text such as `17` is cached as an integer and remains an integer after reload;
- malformed text for a known typed key is normalized to the declared default and the canonical default text is persisted, rather than retaining corrupt text in the database; and
- an **untyped** custom key has no declared decoder, so its canonical database and cache value is its textual serialized representation. A mapping supplied to an untyped key therefore reads consistently as JSON text both immediately and after restart.

Before this contract, `set()` wrote serialized text to PostgreSQL but cached the raw caller value. A CLI boolean write could therefore be a truthy string in the current process and a boolean after the next cache load. The same write changing meaning after restart was a configuration-consistency defect even when the persisted representation itself was parseable.

The write path does not add a new schema, type column, or migration. `DEFAULT_CONFIG_INDEX` remains the authoritative type registry for built-in settings, and unknown keys remain text-backed extension values.

## Operational diagnosis

When a configured boolean appears to have fallen back, inspect the relevant `com_config.config_key` and `config_value` through trusted database administration tooling. Compare the stored text with the accepted vocabulary above. Repair a legacy row with the CLI or a parameterized database update; do not broaden the parser to accept arbitrary prose, whitespace-bearing variants, or Python truthiness.

A fallback to the declared default is safer than raising during process startup because the existing configuration contract already uses declared defaults for malformed integers, floating-point values, mappings, and sequences. It also preserves service availability while preventing malformed text from overriding the reviewed default direction. New writes are canonicalized, so malformed known values are not reintroduced by the supported store API.

## Verification

Deterministic tests prove that:

1. all established true and false spellings remain accepted;
2. a malformed value for a false-default key remains false;
3. the existing true-default key falls back to true;
4. CLI-style boolean and integer strings have the same typed read-after-write and post-reload value;
5. malformed known writes persist the canonical declared default;
6. unknown untyped configuration is cached and reloaded as the same textual representation; and
7. this doctoring and the changelog retain the non-coercive fallback and canonical-write contracts.

The full gate must continue to prove production statement and branch coverage, public docstrings, Python 3.10/3.12/3.14 compatibility, lint, lock freshness, packaging, container builds, SAST, and security checks.

## Rollback

There is no database migration or persistent format change. Code **rollback** is mechanically simple, but it restores two defects: any non-empty malformed boolean string becomes true during deserialization, and configuration writes can cache a different type or value than the text PostgreSQL will return after reload. If compatibility concerns arise, retain declared-default fallback and canonical write normalization and correct the affected `com_config` data rather than restoring truth coercion or raw caller-object caching.

## Reference

Python Software Foundation. (2026). *Truth value testing*. Python 3.14.6 documentation. https://docs.python.org/3/library/stdtypes.html#truth-value-testing
