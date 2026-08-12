# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Bootstrap transport.

This is the ONLY module permitted to read process environment variables, and
only for the two bootstrap secrets needed to *reach* the config/secret stores:

* ``PG_LLM_BATCH_DSN`` — the Postgres DSN (connection string).
* ``PG_LLM_BATCH_SECRET_KEY`` — optional Fernet key to decrypt ``com_secrets``.

Everything else (gateway URL, API key, endpoint alias, token limits, ...) is
read from the database KV stores, never from the environment.
"""

from __future__ import annotations

import os
from typing import Optional

from .exceptions import ConfigError

DSN_ENV_VAR = "PG_LLM_BATCH_DSN"
SECRET_KEY_ENV_VAR = "PG_LLM_BATCH_SECRET_KEY"


def _require_exact_string(value: object, *, label: str) -> str:
    """Return an exact string or fail before lower-layer authority is selected."""
    if type(value) is not str:
        raise ConfigError(f"{label} must be a string.")
    return value


def resolve_dsn(explicit: Optional[str] = None) -> str:
    """Resolve one explicit or environment-backed nonblank Postgres DSN.

    Environment fallback occurs only when ``explicit`` is omitted. Explicit
    values are never replaced merely because they are false-valued or malformed.
    Accepted DSNs are returned byte-for-byte unchanged after validation.
    """
    if explicit is None:
        candidate: object = os.environ.get(DSN_ENV_VAR)
        if candidate is None:
            raise ConfigError(
                f"No Postgres DSN available. Pass --dsn or set {DSN_ENV_VAR} "
                "(bootstrap transport only)."
            )
        label = DSN_ENV_VAR
    else:
        candidate = explicit
        label = "Explicit Postgres DSN"

    dsn = _require_exact_string(candidate, label=label)
    if not dsn.strip():
        raise ConfigError(f"{label} must not be empty or whitespace-only.")
    return dsn


def resolve_secret_key(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the optional Fernet key without replacing explicit empty input.

    An explicit value wins even when it is the empty string, which deliberately
    prevents ambient environment state from silently acquiring decryption
    authority. Non-string explicit values fail before environment fallback.
    """
    if explicit is not None:
        return _require_exact_string(explicit, label="Explicit Fernet key")
    return os.environ.get(SECRET_KEY_ENV_VAR)
