# SPDX-License-Identifier: Apache-2.0
"""Static contracts for retiring the legacy provider-network extensions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIREMENT_SQL = (
    ROOT / "docker" / "postgres" / "migrations" / "retire_legacy_provider_extensions.sql"
)


def _migration() -> str:
    """Return the reviewed legacy-extension retirement migration."""
    return RETIREMENT_SQL.read_text(encoding="utf-8")


def test_retirement_requires_cleanup_before_extension_drop() -> None:
    """Refuse package-era extension removal while jobs or helpers remain."""
    sql = _migration()

    assert "batch-result-retrieval" in sql
    assert "SELECT cron_fetch_batch_results();" in sql
    for signature in (
        "public.cron_fetch_batch_results()",
        "public.import_batch_results_jsonl(uuid,text,text)",
        "public.get_secret_value(text)",
        "public.get_config_value(text)",
    ):
        assert signature in sql
    assert sql.index("batch-result-retrieval") < sql.index(
        "DROP EXTENSION IF EXISTS pg_cron RESTRICT;"
    )


def test_retirement_fails_closed_for_unrelated_cron_jobs() -> None:
    """Do not destroy an operator's independent pg_cron schedules."""
    sql = _migration()

    assert "remaining_job_count" in sql
    assert "cron.job" in sql
    assert "Refusing to retire pg_cron while cron jobs remain" in sql


def test_retirement_uses_restrict_and_preserves_application_data() -> None:
    """Extension cleanup must never cascade through application-owned state."""
    sql = _migration()
    upper = sql.upper()

    assert "DROP EXTENSION IF EXISTS http RESTRICT;" in sql
    assert "DROP EXTENSION IF EXISTS pg_cron RESTRICT;" in sql
    assert "CASCADE" not in upper
    assert "DROP TABLE" not in upper
    assert "DROP SCHEMA" not in upper
    assert "gateway_retrieval_logs" not in sql


def test_retirement_has_finite_lock_wait_and_one_transaction() -> None:
    """Bound migration lock waits and preserve all-or-nothing extension removal."""
    sql = _migration()

    assert sql.count("BEGIN;") == 1
    assert sql.count("COMMIT;") == 1
    assert "SET LOCAL lock_timeout = '5s';" in sql
