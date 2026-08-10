# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for decommissioning direct SQL provider retrieval."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LEGACY_SQL = ROOT / "docker/postgres/init/03_cron_batch_retrieval.sql"
DOCTORING = ROOT / "docs/doctoring/legacy-pgsql-http-retrieval.md"
LEGACY_SOURCE_LITERAL = re.compile(r"\$legacy\$(.*?)\$legacy\$", re.DOTALL)
RETIRED_SECRET_SOURCE = """
DECLARE
    rec RECORD;
BEGIN
    SELECT secret_value, is_encrypted INTO rec
    FROM com_secrets WHERE secret_key = p_key LIMIT 1;
    IF rec IS NULL THEN
        RETURN NULL;
    END IF;
    IF rec.is_encrypted THEN
        -- Encrypted at rest; cannot decrypt inside SQL without the app key.
        RETURN NULL;
    END IF;
    RETURN convert_from(decode(rec.secret_value, 'base64'), 'UTF8');
END;
"""


def _legacy_sql() -> str:
    """Return the bundled legacy-retrieval migration text."""
    return LEGACY_SQL.read_text(encoding="utf-8")


def _executable_cleanup_sql(sql: str) -> str:
    """Return cleanup SQL with inert retired-helper fingerprints removed.

    The cleanup deliberately embeds each historical PL/pgSQL helper body inside a
    ``$legacy$`` dollar-quoted value so ``pg_proc.prosrc`` can be compared against
    the exact retired definition before deletion.  Those values are data used for
    identity verification, not executable provider-network authority.  Strip only
    that reviewed literal class before assertions about executable SQL.
    """
    fingerprints = LEGACY_SOURCE_LITERAL.findall(sql)
    assert len(fingerprints) == 4, "expected one exact source fingerprint per retired helper"
    assert sql.count("helper_source IS DISTINCT FROM $legacy$") == 4
    return LEGACY_SOURCE_LITERAL.sub("<retired-helper-source-fingerprint>", sql)


def test_bundled_sql_never_performs_credential_bearing_provider_http() -> None:
    """Keep provider credentials and remote HTTP outside the database runtime."""
    sql = _legacy_sql()
    executable_sql = _executable_cleanup_sql(sql)

    assert "http_get(" not in executable_sql
    assert "http_header('Authorization'" not in executable_sql
    assert "CREATE OR REPLACE FUNCTION get_secret_value" not in executable_sql
    assert "CREATE OR REPLACE FUNCTION cron_fetch_batch_results" not in executable_sql
    assert "CREATE TABLE IF NOT EXISTS gateway_retrieval_logs" not in executable_sql

    fingerprints = LEGACY_SOURCE_LITERAL.findall(sql)
    assert any("http_get(" in fingerprint for fingerprint in fingerprints)
    assert any("gateway_api_key.default" in fingerprint for fingerprint in fingerprints)


def test_retired_secret_helper_fingerprint_matches_protected_main_source() -> None:
    """Cleanup must recognize the exact secret helper installed by protected main."""
    fingerprints = LEGACY_SOURCE_LITERAL.findall(_legacy_sql())

    assert RETIRED_SECRET_SOURCE in fingerprints


def test_bundled_sql_unschedules_and_removes_the_legacy_retriever() -> None:
    """Make replaying the init script a fail-closed cleanup for old installs."""
    sql = _legacy_sql()

    assert "FROM pg_catalog.pg_extension" in sql
    assert "jobname = 'batch-result-retrieval'" in sql
    assert "command = 'SELECT cron_fetch_batch_results();'" in sql
    assert "cron.unschedule(legacy_job.jobid)" in sql
    for regprocedure in (
        "public.cron_fetch_batch_results()",
        "public.import_batch_results_jsonl(uuid,text,text)",
        "public.get_secret_value(text)",
        "public.get_config_value(text)",
    ):
        assert f"to_regprocedure('{regprocedure}')" in sql
    assert "cron.schedule(" not in sql
    assert "DROP TABLE" not in sql


def test_helper_cleanup_refuses_same_signature_function_substitution() -> None:
    """Do not delete an operator function merely because it reuses a legacy signature."""
    sql = _legacy_sql()

    for legacy_marker in (
        "gateway_api_key.default",
        "llm_requests",
        "com_secrets",
        "com_config",
    ):
        assert legacy_marker in sql
    assert "FROM pg_catalog.pg_proc" in sql
    assert "RAISE EXCEPTION" in sql
    assert "DROP FUNCTION IF EXISTS public." not in sql


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
        "fresh databases no longer create",
        "`pg_cron` or `http`",
        "existing volumes",
        "image packages remain",
        "to_regprocedure('public.cron_fetch_batch_results()')",
        "to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)')",
        "to_regprocedure('public.get_secret_value(text)')",
        "to_regprocedure('public.get_config_value(text)')",
        "same-signature function",
        "fails closed",
        "unschedule is committed",
        "manual review",
    ):
        assert required in doctoring