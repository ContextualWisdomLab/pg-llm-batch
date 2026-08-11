# SPDX-License-Identifier: Apache-2.0
"""Fresh-database extension contracts after retiring direct SQL provider I/O."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS_SQL = ROOT / "docker/postgres/init/01_extensions.sql"


def test_fresh_database_does_not_enable_retired_network_or_scheduler_extensions() -> None:
    """Do not grant fresh installs database-side HTTP or scheduling authority."""
    sql = EXTENSIONS_SQL.read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS pg_cron;" not in sql
    assert "CREATE EXTENSION IF NOT EXISTS http;" not in sql


def test_fresh_database_preserves_required_crypto_and_optional_tokenizer() -> None:
    """Keep package-required crypto and the existing optional tokenizer contract."""
    sql = EXTENSIONS_SQL.read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto;" in sql
    assert "CREATE EXTENSION IF NOT EXISTS pg_tiktoken;" in sql
