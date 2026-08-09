# Typed configuration fallback and canonical writes

## Purpose

Configuration rows in `com_config` are persisted as text and converted back to the type declared by `DEFAULT_CONFIG_INDEX`. Boolean conversion is intentionally finite and non-coercive: accepted values are `true`, `1`, `yes`, and `on` for true, and `false`, `0`, `no`, and `off` for false, matched case-insensitively.

Any other persisted text is a **malformed boolean**. It must not be interpreted using Python's general truth-value rules because every non-empty string is true. Instead, the loader returns the setting's **declared default**. This is especially important for a **false-default** feature flag: corrupt or manually mistyped text cannot silently enable behavior that operators and code declared disabled by default.

JSON-backed mapping and sequence settings have a second boundary. Syntactically **valid JSON** is not sufficient when its **container shape** contradicts the **declared collection type**. An array cannot satisfy a mapping contract, and an object cannot satisfy a sequence contract merely because both parse successfully. A shape mismatch returns the declared default exactly like malformed JSON.

Mutable collection defaults are process-wide type-registry metadata, not caller-owned working state. Returning the same mapping or sequence object would let one **caller mutation** change the default observed by every later cache miss, malformed-value fallback, or configuration write in that process. Every declared fallback is therefore returned as an **isolated copy**; nested mutable members are isolated as well. The authoritative **process-wide default** remains unchanged.

Unknown keys have no registry-owned default to protect. Their fallback argument remains caller-owned and is returned unchanged. This preserves **unknown caller fallback identity**, avoids invoking arbitrary copying hooks on host objects, and retains the pre-existing `get(..., default=sentinel)` compatibility contract.

## Runtime contract

- Known boolean spellings retain their existing values.
- A malformed boolean value returns the exact default recorded for that configuration key.
- A key with boolean type metadata but no declared item fails closed to `False`.
- A mapping setting accepts only a decoded JSON object; a decoded array, scalar, or null returns the declared mapping default.
- A sequence setting accepts only a decoded JSON array; a decoded object, scalar, or null returns the declared sequence default.
- Mutable mapping, sequence, and nested declared defaults are copied before they cross the registry boundary, so caller mutation cannot corrupt later defaults.
- An unknown key returns the exact caller-supplied fallback object without copying, coercing, serializing, or invoking `__deepcopy__`.
- A mapping or sequence already held by the in-memory cache is returned through a defensive copy, so callers cannot mutate persisted cache state without an explicit `set()` operation.
- Integer, floating-point, and untyped custom-value read behavior remains deterministic.
- The fallback does not make malformed external data valid. Operators should correct an affected legacy `com_config` row after diagnosis.
- No credential, provider response, prompt, tenant identifier, or configuration value is added to public telemetry by this change.

This behavior is deterministic across cache initialization, a cache miss, and `show_config()`, because all three typed read paths use the same `_deserialize_value()` function. Missing-row lookup isolates a known registry default but preserves an unknown caller fallback unchanged.

## Canonical write and cache contract

`PostgresConfigStore.set()` applies the same type contract before it updates either PostgreSQL or the in-memory cache. It serializes the caller's value, deserializes that text through the declared configuration type, and then persists the **canonical** serialized result. The normalized value—not the caller's untyped object—is stored in the cache.

The cache owns its mutable mapping and sequence values. `PostgresConfigStore.get()` therefore returns a **defensive copy** of every **cache-owned mutable value** on both a cache hit and the first database-backed load. A caller may freely mutate the returned value, but the **persisted cache state** and later reads remain unchanged until the caller explicitly invokes `set()`. Scalar values remain direct immutable values, and an unknown missing-key fallback retains caller identity because it is never inserted into the cache.

This gives one **read-after-write** result across process boundaries:

- CLI text such as `false` is cached immediately as the boolean `False` and is still `False` after a **cache reload**;
- numeric CLI text such as `17` is cached as an integer and remains an integer after reload;
- malformed text or wrong-shaped valid JSON for a known typed key is normalized to an isolated copy of the declared default and the canonical default text is persisted, rather than retaining corrupt or contradictory data in the database;
- mutating a declared fallback returned to one caller cannot change the registry value used by a later write or reload;
- mutating a mapping or sequence returned from a cache hit, canonical write, or database reload cannot change the cache-owned value observed by later readers;
- an unknown missing-key fallback remains the caller's exact object and is not promoted into registry or cache state; and
- an **untyped** custom key has no declared decoder, so its canonical database and cache value is its textual serialized representation. A mapping supplied to an untyped key therefore reads consistently as JSON text both immediately and after restart.

Before this contract, `set()` wrote serialized text to PostgreSQL but cached the raw caller value. A CLI boolean write could therefore be a truthy string in the current process and a boolean after the next cache load. The same write changing meaning after restart was a configuration-consistency defect even when the persisted representation itself was parseable. Separately, returning a mutable registry default directly allowed caller-owned state to become process-wide configuration metadata, and returning a cached mapping or sequence directly let a read mutate package-owned state without persistence.

The write path does not add a new schema, type column, or migration. `DEFAULT_CONFIG_INDEX` remains the authoritative type registry for built-in settings, and unknown keys remain text-backed extension values.

## Operational diagnosis

When a configured value appears to have fallen back, inspect the relevant `com_config.config_key` and `config_value` through trusted database administration tooling. For booleans, compare the stored text with the accepted vocabulary above. For a mapping or sequence, verify both JSON syntax and the top-level JSON type defined by RFC 8259. Repair a legacy row with the CLI or a parameterized database update; do not broaden the parser to accept arbitrary prose, whitespace-bearing boolean variants, Python truthiness, or the wrong JSON container type.

A fallback to the declared default is safer than raising during process startup because the existing configuration contract already uses declared defaults for malformed integers, floating-point values, mappings, and sequences. It also preserves service availability while preventing malformed or contradictory text from overriding the reviewed default direction. New writes are canonicalized, so malformed known values are not reintroduced by the supported store API. Fallback copies protect only registry-owned metadata; callers remain responsible for the lifetime and mutation of fallback objects they explicitly supply for unknown keys. Cached collection copies protect the store's internal read state; they are not an optimistic-locking or multi-process synchronization mechanism.

## Verification

Deterministic tests prove that:

1. all established true and false spellings remain accepted;
2. a malformed value for a false-default key remains false;
3. the existing true-default key falls back to true;
4. valid JSON with the wrong collection shape returns the declared mapping or sequence default;
5. valid JSON with the correct declared collection type retains its configured value;
6. mapping and sequence fallbacks are not the same objects as their registry defaults;
7. mutating returned declared fallbacks or known missing-row defaults does not change later fallback results, including nested mutable state;
8. an unknown-key fallback preserves caller identity and can be deliberately non-copyable;
9. mutating a mapping returned after cache initialization, canonical `set()`, or cache reload does not change later reads;
10. CLI-style boolean and integer strings have the same typed read-after-write and post-reload value;
11. malformed known writes persist the canonical declared default;
12. unknown untyped configuration is cached and reloaded as the same textual representation; and
13. this doctoring and the changelog retain the non-coercive fallback, declared collection type, mutable-default isolation, mutable-cache isolation, caller-fallback compatibility, and canonical-write contracts.

The full gate must continue to prove production statement and branch coverage, public docstrings, Python 3.10/3.12/3.14 compatibility, lint, lock freshness, packaging, container builds, SAST, and security checks.

## Rollback

There is no database migration or persistent format change. Code **rollback** is mechanically simple, but it restores five defects: any non-empty malformed boolean string becomes true during deserialization, valid JSON with a contradictory container shape can violate a declared mapping or sequence type, configuration writes can cache a different type or value than the text PostgreSQL will return after reload, a caller can mutate process-wide collection defaults through a returned declared fallback object, and a caller can mutate a cache-owned collection through an ordinary read. If compatibility concerns arise, retain declared-default fallback, exact collection-shape validation, isolated mutable defaults, preserved unknown caller fallback identity, mutable-cache defensive copies, and canonical write normalization and correct the affected `com_config` data rather than restoring truth coercion, shape ambiguity, shared mutable registry state, mutable cache exposure, or raw caller-object caching.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format* (RFC 8259). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc8259.html

Python Software Foundation. (2026). *Truth value testing*. Python 3.14.6 documentation. https://docs.python.org/3/library/stdtypes.html#truth-value-testing
