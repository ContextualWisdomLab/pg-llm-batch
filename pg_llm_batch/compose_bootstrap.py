# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Start the standalone health service with a mounted PostgreSQL password secret.

The Compose profile keeps the database password out of committed configuration,
process arguments, and the credential-free bootstrap DSN. This module reads the
single explicitly mounted secret, combines it with the bootstrap target only in
process memory through the selected PostgreSQL driver boundary, and hands the
result directly to the existing health server.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .bootstrap import resolve_dsn
from .exceptions import ConfigError
from .health import serve_healthz
from .postgres_driver_port import PostgresDriverPort

try:  # pragma: no cover - retained optional dependency during migration
    from psycopg.conninfo import make_conninfo as _psycopg_make_conninfo
except ImportError:  # pragma: no cover
    _psycopg_make_conninfo = None

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
        raise ConfigError(
            "The mounted PostgreSQL password secret is not valid UTF-8."
        ) from None

    if "\x00" in password or "\r" in password or "\n" in password:
        raise ConfigError("The mounted PostgreSQL password secret has invalid framing.")
    return password


def _build_private_dsn(
    base_dsn: str,
    password: str,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> str:
    """Add the mounted password through the selected reviewed conninfo renderer.

    An injected replacement driver parses the credential-free selector and then
    renders a fresh parameter snapshot containing the mounted password. The
    retained Psycopg renderer remains the default only while the commercial
    migration is incomplete. Parser or renderer diagnostics are normalized so
    secret material never escapes this bootstrap boundary.
    """
    try:
        if postgres_driver is not None:
            parameters = dict(postgres_driver.parse_conninfo(base_dsn))
            parameters["password"] = password
            return postgres_driver.make_conninfo(parameters)
        if _psycopg_make_conninfo is None:
            raise ConfigError("The PostgreSQL bootstrap driver is unavailable.")
        return _psycopg_make_conninfo(base_dsn, password=password)
    except ConfigError:
        raise
    except Exception:
        raise ConfigError("The PostgreSQL bootstrap target is invalid.") from None


def run_compose_health(
    password_file: Path = _DEFAULT_PASSWORD_FILE,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> None:
    """Serve readiness with one driver owning private DSN assembly and database I/O."""
    base_dsn = resolve_dsn(None)
    password = _load_database_password(password_file)
    private_dsn = _build_private_dsn(
        base_dsn,
        password,
        postgres_driver=postgres_driver,
    )
    if postgres_driver is None:
        serve_healthz(private_dsn, host="0.0.0.0", port=8080)
        return
    serve_healthz(
        private_dsn,
        host="0.0.0.0",
        port=8080,
        postgres_driver=postgres_driver,
    )


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


if __name__ == "__main__":
    main()
