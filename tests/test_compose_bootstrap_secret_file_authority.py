# SPDX-License-Identifier: Apache-2.0
"""Regression tests for mounted Compose secret file authority."""

from __future__ import annotations

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
