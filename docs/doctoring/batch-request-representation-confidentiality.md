# BatchRequest representation confidentiality

## Scope and status

This note documents the bounded representation-confidentiality change carried by ACTIVE-PR #104. It is not a protected-main guarantee until that pull request or an equivalent successor is integrated and revalidated against the then-current protected head.

`BatchRequest` contains caller-provided request content. `user_prompt` can contain personal, confidential, regulated, or proprietary material; `system_prompt` can contain protected instructions; and the caller-selected `id` can itself be operationally sensitive. A generic Python object representation is therefore not an appropriate package-owned disclosure surface for those fields.

## Decision

The data-class fields `user_prompt`, `system_prompt`, and `id` use the standard-library data-class field representation control with `repr=False`. The non-secret `model` field remains present in the generated representation so routine diagnostics retain useful type/model context without reproducing request content.

This is deliberately narrower than masking or destructive transformation. The original values remain available to authorized application code through their public attributes and continue to participate in ordinary data-class equality exactly as before. The change only prevents the generated `repr()` — and therefore the default `str()` inherited from that representation — from copying those values into generic object rendering.

## Non-goals and residual boundary

A safe generated representation is not a general serialization policy. Direct attribute access, `vars()` / `__dict__`, `dataclasses.asdict()`, pickling, caller-defined serializers, database persistence, provider submission, and application-owned logs are separate authority boundaries. They are not made redacted by `repr=False`, and this change must not be used to claim otherwise.

The package therefore prefers purpose-bound access and selective disclosure over blanket masking: request content remains usable for its intended batching function, while an incidental diagnostics surface stops duplicating it.

## Compatibility

The constructor signature is unchanged, but runtime accepted values are intentionally narrowed by #104: `user_prompt`, `model`, and `id` require exact `str` values, while `system_prompt` accepts only `None` or an exact `str`. Empty strings remain accepted for compatibility. Equality semantics remain unchanged because the fields continue to use the data-class default `compare=True`; only representation participation changes. No schema, provider transport, credential, CLI, persistence, or release interface changes.

## Verification

The focused regression constructs a `BatchRequest` with unique sentinels in `user_prompt`, `system_prompt`, and `id`, then proves those sentinels are absent from both `repr(request)` and `str(request)` while the model identifier remains visible. Repository acceptance additionally requires supported Python 3.10, 3.12, and 3.14 tests, exact owned production statement/branch coverage, public docstring coverage, package/container checks, SAST, security scanning, and the live exact-source governance applicable at integration time.

## Rollback

If an embedding application demonstrably depends on the previous generated representation, do not restore content-bearing representations silently. Revert the representation change only through a reviewed compatibility decision that explicitly accepts the disclosure consequence, or provide an application-owned diagnostic formatter whose disclosure policy is appropriate to that deployment.

## References

Python Software Foundation. (2026). *dataclasses — Data classes: Python 3.14.6 documentation*. https://docs.python.org/3.14/library/dataclasses.html

The Python documentation specifies that generated data-class representations include fields by default and that the `repr` parameter on `field()` controls whether a field appears in that generated representation.