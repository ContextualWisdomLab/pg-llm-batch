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
    """Resolve the Postgres DSN.

    Precedence: an explicit argument (e.g. ``--dsn``) wins; otherwise the
    bootstrap env var is consulted. Raises if neither is available.
    """
    dsn = explicit or os.environ.get(DSN_ENV_VAR)
    if not dsn:
        raise ConfigError(
            f"No Postgres DSN available. Pass --dsn or set {DSN_ENV_VAR} "
            "(bootstrap transport only)."
        )
    return dsn


def resolve_secret_key(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the optional Fernet key used to decrypt secrets at rest."""
    return explicit or os.environ.get(SECRET_KEY_ENV_VAR)
