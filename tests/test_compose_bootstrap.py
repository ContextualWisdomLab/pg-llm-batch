# SPDX-License-Identifier: Apache-2.0
"""Tests for the standalone Compose mounted-secret bootstrap boundary."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

from pg_llm_batch import compose_bootstrap
from pg_llm_batch.exceptions import ConfigError


def test_load_database_password_preserves_safe_special_characters(tmp_path: Path) -> None:
    """Mounted secret text must retain characters that require conninfo quoting."""
    password_file = tmp_path / "database-password"
    password_file.write_text(r"pa:ss\\word with spaces='quoted'", encoding="utf-8")

    assert compose_bootstrap._load_database_password(password_file) == (
        r"pa:ss\\word with spaces='quoted'"
    )


@pytest.mark.parametrize(
    ("raw_password", "expected_message"),
    [
        (b"", "is empty"),
        (b"bad\npassword", "invalid framing"),
        (b"bad\rpassword", "invalid framing"),
        (b"bad\x00password", "invalid framing"),
        (b"\xff", "not valid UTF-8"),
    ],
)
def test_load_database_password_fails_closed_without_secret_echo(
    tmp_path: Path, raw_password: bytes, expected_message: str
) -> None:
    """Malformed secret files must fail with fixed content-free diagnostics."""
    password_file = tmp_path / "database-password"
    password_file.write_bytes(raw_password)

    with pytest.raises(ConfigError) as caught:
        compose_bootstrap._load_database_password(password_file)

    assert expected_message in str(caught.value)
    assert repr(raw_password) not in str(caught.value)
    assert caught.value.__cause__ is None


def test_load_database_password_rejects_oversize_and_missing_files(
    tmp_path: Path,
) -> None:
    """Secret reads must be finite and missing mounts must fail closed."""
    oversize_file = tmp_path / "oversize-password"
    oversize_file.write_bytes(b"a" * 65_537)

    with pytest.raises(ConfigError, match="size limit"):
        compose_bootstrap._load_database_password(oversize_file)

    with pytest.raises(ConfigError, match="unavailable"):
        compose_bootstrap._load_database_password(tmp_path / "missing-password")


def test_build_private_dsn_quotes_password_without_manual_interpolation() -> None:
    """Special password characters must be supplied as a conninfo field."""
    password = r"colon:backslash\\space value='quoted'"

    private_dsn = compose_bootstrap._build_private_dsn(
        "postgresql://pgllm@postgres:5432/pgllm", password
    )
    parsed = conninfo_to_dict(private_dsn)

    assert parsed["user"] == "pgllm"
    assert parsed["host"] == "postgres"
    assert parsed["port"] == "5432"
    assert parsed["dbname"] == "pgllm"
    assert parsed["password"] == password


def test_build_private_dsn_uses_fixed_error_for_invalid_target() -> None:
    """Psycopg parser details must not escape through the Compose boundary."""
    with pytest.raises(ConfigError, match="bootstrap target is invalid") as caught:
        compose_bootstrap._build_private_dsn("postgresql://[", "dont-print-me")

    assert "dont-print-me" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_run_compose_health_combines_secret_only_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The health server must receive the quoted private DSN, not secret argv/env."""
    password_file = tmp_path / "database-password"
    password = r"pa:ss\\word with spaces"
    password_file.write_text(password, encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        compose_bootstrap,
        "resolve_dsn",
        lambda explicit=None: "postgresql://pgllm@postgres:5432/pgllm",
    )

    def capture_server(dsn: str, host: str, port: int) -> None:
        captured.update(dsn=dsn, host=host, port=port)

    monkeypatch.setattr(compose_bootstrap, "serve_healthz", capture_server)

    compose_bootstrap.run_compose_health(password_file)

    parsed = conninfo_to_dict(str(captured["dsn"]))
    assert parsed["password"] == password
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8080


def test_password_file_argument_is_path_only(tmp_path: Path) -> None:
    """CLI parsing must expose only a non-secret mounted-file path."""
    password_file = tmp_path / "database-password"

    assert compose_bootstrap._password_file_from_args(
        ["--password-file", str(password_file)]
    ) == password_file
    assert compose_bootstrap._password_file_from_args([]) == Path(
        "/run/secrets/postgres_password"
    )


def test_main_delegates_to_password_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module entry function must pass only the parsed path to the runner."""
    password_file = tmp_path / "database-password"
    captured: list[Path] = []
    monkeypatch.setattr(compose_bootstrap, "run_compose_health", captured.append)

    compose_bootstrap.main(["--password-file", str(password_file)])

    assert captured == [password_file]


def test_module_execution_invokes_health_without_secret_in_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m`` execution must use the mounted secret and credential-free argv."""
    password_file = tmp_path / "database-password"
    password_file.write_text("module-special:pass\\word", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setenv(
        "PG_LLM_BATCH_DSN", "postgresql://pgllm@postgres:5432/pgllm"
    )

    def capture_server(dsn: str, host: str, port: int) -> None:
        captured.update(dsn=dsn, host=host, port=port)

    import pg_llm_batch.health as health_module

    monkeypatch.setattr(health_module, "serve_healthz", capture_server)
    monkeypatch.setattr(
        sys,
        "argv",
        ["compose_bootstrap", "--password-file", str(password_file)],
    )

    runpy.run_module("pg_llm_batch.compose_bootstrap", run_name="__main__")

    parsed = conninfo_to_dict(str(captured["dsn"]))
    assert parsed["password"] == "module-special:pass\\word"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8080
