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


def resolve_dsn(explicit: Optional[str] = None) -> str:
    """Resolve a nonblank Postgres DSN without overriding explicit operator intent.

    A supplied explicit argument (for example ``--dsn``) always owns the
    database-target decision. It must be an exact string; empty, whitespace-only,
    or non-string explicit inputs fail closed before environment fallback. The
    environment is consulted only when the explicit argument is omitted entirely.
    Valid DSN strings are returned unchanged.
    """
    if explicit is not None:
        if not isinstance(explicit, str):
            raise ConfigError("An explicit Postgres DSN must be a string")
        if explicit.strip() == "":
            raise ConfigError(
                "An explicit Postgres DSN must not be empty or whitespace-only; "
                f"omit --dsn to use {DSN_ENV_VAR}."
            )
        return explicit

    dsn = os.environ.get(DSN_ENV_VAR)
    if dsn is None or dsn.strip() == "":
        raise ConfigError(
            f"No nonblank Postgres DSN available. Pass --dsn or set {DSN_ENV_VAR} "
            "(bootstrap transport only)."
        )
    return dsn


def resolve_secret_key(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the optional Fernet key while preserving explicit absence.

    The environment is consulted only when the caller omits the argument.
    Supplying an empty string explicitly disables the ambient bootstrap key
    rather than silently selecting a different decryption authority. Any other
    explicit value must be a string so invalid caller types fail at the bootstrap
    authority boundary instead of reaching the secret store.
    """
    if explicit is not None:
        if not isinstance(explicit, str):
            raise ConfigError("An explicit Fernet bootstrap key must be a string")
        return explicit
    return os.environ.get(SECRET_KEY_ENV_VAR)
