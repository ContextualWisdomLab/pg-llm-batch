# SPDX-License-Identifier: Apache-2.0
"""Regression tests for mounted Compose secret file authority."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pg_llm_batch import compose_bootstrap
from pg_llm_batch.exceptions import ConfigError


def test_database_password_loader_rejects_final_symlink(tmp_path: Path) -> None:
    """A mounted-secret pathname cannot redirect authority through a symlink."""
    secret_text = "private-compose-password"
    target = tmp_path / "actual-password"
    target.write_text(secret_text, encoding="utf-8")
    mounted_path = tmp_path / "mounted-password"
    mounted_path.symlink_to(target)

    with pytest.raises(ConfigError, match="unavailable") as caught:
        compose_bootstrap._load_database_password(mounted_path)

    assert secret_text not in str(caught.value)
    assert caught.value.__cause__ is None


def test_database_password_loader_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    """A non-regular mounted object fails closed before any secret read."""
    fifo_path = tmp_path / "mounted-password"
    os.mkfifo(fifo_path)

    with pytest.raises(ConfigError, match="unavailable") as caught:
        compose_bootstrap._load_database_password(fifo_path)

    assert caught.value.__cause__ is None


def test_database_password_loader_fails_closed_without_secure_open_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A platform without no-follow authority cannot silently downgrade the open."""
    password_file = tmp_path / "database-password"
    password_file.write_text("private-compose-password", encoding="utf-8")
    monkeypatch.delattr(compose_bootstrap.os, "O_NOFOLLOW")

    with pytest.raises(ConfigError, match="unavailable") as caught:
        compose_bootstrap._load_database_password(password_file)

    assert caught.value.__cause__ is None


def test_database_password_loader_normalizes_fstat_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Descriptor metadata failures stay content-free and close the retained fd."""
    password_file = tmp_path / "database-password"
    password_file.write_text("private-compose-password", encoding="utf-8")

    def fail_fstat(_fd: int) -> os.stat_result:
        raise OSError("sensitive stat diagnostic")

    monkeypatch.setattr(compose_bootstrap.os, "fstat", fail_fstat)

    with pytest.raises(ConfigError, match="unavailable") as caught:
        compose_bootstrap._load_database_password(password_file)

    assert "sensitive stat diagnostic" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_database_password_loader_normalizes_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A descriptor-close failure invalidates otherwise valid secret evidence."""
    password_file = tmp_path / "database-password"
    secret_text = "private-compose-password"
    password_file.write_text(secret_text, encoding="utf-8")
    real_close = compose_bootstrap.os.close

    def close_then_fail(fd: int) -> None:
        real_close(fd)
        raise OSError("sensitive close diagnostic")

    monkeypatch.setattr(compose_bootstrap.os, "close", close_then_fail)

    with pytest.raises(ConfigError, match="unavailable") as caught:
        compose_bootstrap._load_database_password(password_file)

    assert secret_text not in str(caught.value)
    assert "sensitive close diagnostic" not in str(caught.value)
    assert caught.value.__cause__ is None
