# SPDX-License-Identifier: Apache-2.0
"""Regression tests for Compose bootstrap through the PostgreSQL driver port."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pg_llm_batch import compose_bootstrap


class _BootstrapDriver:
    """Capture conninfo and health-service use without importing a concrete driver."""

    def __init__(self) -> None:
        self.parsed: list[str] = []
        self.rendered: list[dict[str, str]] = []

    def parse_conninfo(self, dsn: str) -> Mapping[str, str]:
        """Return the credential-free target fields expected by the bootstrap."""
        self.parsed.append(dsn)
        return {
            "user": "pgllm",
            "host": "postgres",
            "port": "5432",
            "dbname": "pgllm",
        }

    def make_conninfo(self, params: Mapping[str, str]) -> str:
        """Record the exact private parameter map and return an opaque DSN."""
        snapshot = dict(params)
        self.rendered.append(snapshot)
        return "driver-private-dsn"


def test_build_private_dsn_uses_injected_driver_without_legacy_renderer() -> None:
    """Mounted-secret assembly must be usable after the Psycopg renderer is removed."""
    driver = _BootstrapDriver()

    private_dsn = compose_bootstrap._build_private_dsn(
        "postgresql://pgllm@postgres:5432/pgllm",
        "private-password",
        postgres_driver=driver,  # type: ignore[arg-type]
    )

    assert private_dsn == "driver-private-dsn"
    assert driver.parsed == ["postgresql://pgllm@postgres:5432/pgllm"]
    assert driver.rendered == [
        {
            "user": "pgllm",
            "host": "postgres",
            "port": "5432",
            "dbname": "pgllm",
            "password": "private-password",
        }
    ]


def test_run_compose_health_forwards_one_driver_to_dsn_and_health_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """One selected driver must own both secret-safe DSN assembly and readiness I/O."""
    password_file = tmp_path / "database-password"
    password_file.write_text("private-password", encoding="utf-8")
    driver = _BootstrapDriver()
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        compose_bootstrap,
        "resolve_dsn",
        lambda explicit=None: "postgresql://pgllm@postgres:5432/pgllm",
    )

    def capture_health(
        dsn: str,
        host: str,
        port: int,
        *,
        postgres_driver=None,
    ) -> None:
        observed.update(
            dsn=dsn,
            host=host,
            port=port,
            postgres_driver=postgres_driver,
        )

    monkeypatch.setattr(compose_bootstrap, "serve_healthz", capture_health)

    compose_bootstrap.run_compose_health(
        password_file,
        postgres_driver=driver,  # type: ignore[arg-type]
    )

    assert observed == {
        "dsn": "driver-private-dsn",
        "host": "0.0.0.0",
        "port": 8080,
        "postgres_driver": driver,
    }
