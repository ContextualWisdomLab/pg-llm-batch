# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for decommissioning direct SQL provider retrieval."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_SQL = ROOT / "docker/postgres/init/03_cron_batch_retrieval.sql"
DOCTORING = ROOT / "docs/doctoring/legacy-pgsql-http-retrieval.md"


def _legacy_sql() -> str:
    """Return the bundled legacy-retrieval migration text."""
    return LEGACY_SQL.read_text(encoding="utf-8")


def test_bundled_sql_never_performs_credential_bearing_provider_http() -> None:
    """Keep provider credentials and remote HTTP outside the database runtime."""
    sql = _legacy_sql()

    assert "http_get(" not in sql
    assert "http_header('Authorization'" not in sql
    assert "CREATE OR REPLACE FUNCTION get_secret_value" not in sql
    assert "CREATE OR REPLACE FUNCTION cron_fetch_batch_results" not in sql
    assert "CREATE TABLE IF NOT EXISTS gateway_retrieval_logs" not in sql


def test_bundled_sql_unschedules_and_removes_the_legacy_retriever() -> None:
    """Make replaying the init script a fail-closed cleanup for old installs."""
    sql = _legacy_sql()

    assert "FROM pg_catalog.pg_extension" in sql
    assert "jobname = 'batch-result-retrieval'" in sql
    assert "command = 'SELECT cron_fetch_batch_results();'" in sql
    assert "cron.unschedule(legacy_job.jobid)" in sql
    for signature in (
        "cron_fetch_batch_results()",
        "import_batch_results_jsonl(UUID, TEXT, TEXT)",
        "get_secret_value(TEXT)",
        "get_config_value(TEXT)",
    ):
        assert f"DROP FUNCTION IF EXISTS public.{signature}" in sql
    assert "cron.schedule(" not in sql
    assert "DROP TABLE" not in sql


def test_legacy_retrieval_doctoring_preserves_upgrade_and_authority_boundaries() -> None:
    """Keep existing-volume remediation and the authoritative provider path explicit."""
    doctoring = DOCTORING.read_text(encoding="utf-8")

    for required in (
        "BatchAPIClient",
        "DurableBatchAPIClient",
        "batch-result-retrieval",
        "cron.unschedule",
        "existing volume",
        "same job owner",
        "does not drop",
        "llm_remote_batch_jobs",
        "local batch UUID",
        "Fernet",
        "to_regprocedure('public.cron_fetch_batch_results()')",
        "to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)')",
        "to_regprocedure('public.get_secret_value(text)')",
        "to_regprocedure('public.get_config_value(text)')",
    ):
        assert required in doctoring
