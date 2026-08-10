# Health listener input validation

## Purpose

This note refines the listener-address boundary decided by [ADR 0014](../adr/0014-public-healthz-readiness.md). It does not create a second network-exposure policy. ADR 0014 remains authoritative for the loopback-by-default CLI, explicit container `0.0.0.0` opt-in, public readiness redaction, bounded admission, and deployment-owned ingress/authentication boundary.

`serve_healthz()` must reject malformed listener inputs **before socket-server construction**. This keeps validation in the package boundary instead of depending on operating-system resolver/socket error text, implicit coercion, or implementation-specific parsing.

## Current contract

The listener host must be an explicit Python string that is:

- non-empty;
- unchanged by `str.strip()` (leading or trailing whitespace is invalid);
- free of whitespace characters anywhere; and
- free of ASCII control characters, including C0 (`U+0000`–`U+001F`) and DEL (`U+007F`).

The package does **not** trim, rewrite, stringify, or silently normalize a supplied host. An accepted host is passed to the socket server unchanged. DNS/address syntax and resolution remain operating-system/socket responsibilities after this package-level lexical boundary; this validation is intentionally not a replacement DNS parser.

The listener port must be an actual Python `int` but not `bool`, and must be in the inclusive TCP range `1`–`65535`. Strings, floats, booleans, zero, negative values, and values above `65535` fail before socket creation.

## Security and operability rationale

The public health listener is an operator-controlled network boundary. Silently trimming or coercing malformed values can turn configuration mistakes into a different listener target than the caller supplied. Allowing control characters to reach lower networking layers also makes failure behavior dependent on platform resolver/socket handling and can surface lower-level diagnostics instead of one bounded package error.

Failing closed with `ValidationError` preserves explicit operator intent and produces one package-owned error class without broadening the listener. This is input validation only: it does not authenticate clients, authorize exposure, prove that a hostname resolves safely, or replace deployment firewall/ingress controls.

## Test-first evidence

`tests/test_health_listener_validation.py` protects this boundary with an HTTP-server double that raises if invalid input reaches socket construction.

The first fail-first extension covered leading/trailing whitespace, newline, and NUL-bearing host text. A later regression added ASCII DEL (`U+007F`) because DEL is a control character but is neither whitespace nor below `U+0020`; the predecessor validation therefore allowed it to reach server construction. Production validation was then expanded to reject DEL while preserving already-accepted hosts unchanged.

The same test module separately proves blank hosts and invalid port types/ranges fail before socket construction.

## Recovery and rollback

If an operator-supplied host is rejected, correct the configuration rather than weakening the validation or restoring an all-interface default. If a legitimate platform hostname requires syntax outside this lexical contract, treat that as a reviewed compatibility change with a fail-first regression; do not add ad hoc trimming or coercion.

No database schema, provider protocol, credential, durable state, or release artifact format changes are involved. Reverting this validation is mechanically simple but would re-open platform-dependent malformed-input handling and should therefore be treated as a security/operability regression rather than a harmless rollback.
