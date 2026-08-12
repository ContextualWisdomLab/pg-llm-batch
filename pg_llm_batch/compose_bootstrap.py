# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Start the standalone health service with a mounted PostgreSQL password secret.

The Compose profile keeps the database password out of committed configuration,
process arguments, and the credential-free bootstrap DSN.  This module reads the
single explicitly mounted secret, combines it with the bootstrap target only in
process memory using psycopg's conninfo quoting, and hands the result directly to
the existing health server.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from psycopg.conninfo import make_conninfo

from .bootstrap import resolve_dsn
from .exceptions import ConfigError
from .health import serve_healthz

_DEFAULT_PASSWORD_FILE = Path("/run/secrets/postgres_password")
_MAX_PASSWORD_BYTES = 65_536


def _load_database_password(password_file: Path) -> str:
    """Read one bounded UTF-8 password from an explicitly mounted secret file."""
    try:
        with password_file.open("rb") as secret_stream:
            raw_password = secret_stream.read(_MAX_PASSWORD_BYTES + 1)
    except OSError:
        raise ConfigError("The mounted PostgreSQL password secret is unavailable.") from None

    if not raw_password:
        raise ConfigError("The mounted PostgreSQL password secret is empty.")
    if len(raw_password) > _MAX_PASSWORD_BYTES:
        raise ConfigError("The mounted PostgreSQL password secret exceeds its size limit.")

    try:
        password = raw_password.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ConfigError("The mounted PostgreSQL password secret is not valid UTF-8.") from None

    if "\x00" in password or "\r" in password or "\n" in password:
        raise ConfigError("The mounted PostgreSQL password secret has invalid framing.")
    return password


def _build_private_dsn(base_dsn: str, password: str) -> str:
    """Add the password to a validated DSN using psycopg's conninfo quoting."""
    try:
        return make_conninfo(base_dsn, password=password)
    except Exception:
        raise ConfigError("The PostgreSQL bootstrap target is invalid.") from None


def run_compose_health(password_file: Path = _DEFAULT_PASSWORD_FILE) -> None:
    """Serve health checks using the credential-free DSN plus mounted secret."""
    base_dsn = resolve_dsn(None)
    password = _load_database_password(password_file)
    private_dsn = _build_private_dsn(base_dsn, password)
    serve_healthz(private_dsn, host="0.0.0.0", port=8080)


def _password_file_from_args(argv: Sequence[str] | None) -> Path:
    """Parse the non-secret password-file path from process arguments."""
    parser = argparse.ArgumentParser(
        description="Start pg-llm-batch health checks with a mounted database secret."
    )
    parser.add_argument(
        "--password-file",
        default=str(_DEFAULT_PASSWORD_FILE),
        help="Path to the mounted PostgreSQL password secret.",
    )
    arguments = parser.parse_args(argv)
    return Path(arguments.password_file)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Compose bootstrap entry point without accepting secret text in argv."""
    run_compose_health(_password_file_from_args(argv))


if __name__ == "__main__":  # pragma: no cover - exercised by container command
    main()
