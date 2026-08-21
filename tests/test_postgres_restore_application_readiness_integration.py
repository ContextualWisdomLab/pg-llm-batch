# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL coverage for restore application-readiness inspection."""

from __future__ import annotations

import os

import pytest

from pg_llm_batch import db
from pg_llm_batch.postgres_restore_application_readiness import (
    PostgresRestoreApplicationReadinessError,
    inspect_postgres_restore_application_readiness,
)

pytestmark = pytest.mark.integration

DSN = os.environ.get("PG_LLM_BATCH_TEST_DSN")

skip_no_db = pytest.mark.skipif(
    not DSN, reason="PG_LLM_BATCH_TEST_DSN not set; skipping live-DB integration"
)


@skip_no_db
def test_live_restore_application_readiness_accepts_packaged_schema() -> None:
    """A live packaged schema satisfies the fixed database-side contract."""
    import psycopg

    db.apply_schema(DSN)
    with psycopg.connect(DSN) as connection:
        evidence = inspect_postgres_restore_application_readiness(connection)

    assert evidence.as_dict() == {
        "database_reachable": True,
        "pg_tiktoken_extension_present": True,
        "tiktoken_count_callable": True,
        "tiktoken_encode_callable": True,
        "config_table_readable": True,
        "health_function_count": 1,
        "health_function_executable": True,
    }


@pytest.mark.parametrize(
    "replacement_sql",
    [
        """
        CREATE FUNCTION pg_llm_batch_health_check()
        RETURNS TABLE(component TEXT, is_ready BOOLEAN)
        LANGUAGE SQL
        AS $$ SELECT 'database'::TEXT, TRUE $$
        """,
        """
        CREATE FUNCTION pg_llm_batch_health_check()
        RETURNS TABLE(component TEXT, is_ready BOOLEAN, detail TEXT)
        LANGUAGE SQL
        SECURITY DEFINER
        AS $$ SELECT 'database'::TEXT, TRUE, 'reachable'::TEXT $$
        """,
    ],
    ids=("wrong-result-contract", "security-definer"),
)
@skip_no_db
def test_live_restore_application_readiness_rejects_health_impostors(
    replacement_sql: str,
) -> None:
    """Callable same-name health impostors fail the live catalog contract."""
    import psycopg

    db.apply_schema(DSN)
    with psycopg.connect(DSN) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute("DROP FUNCTION pg_llm_batch_health_check()")
                cursor.execute(replacement_sql)

            with pytest.raises(
                PostgresRestoreApplicationReadinessError,
                match="^PostgreSQL restore target health contract is unavailable$",
            ):
                inspect_postgres_restore_application_readiness(connection)
        finally:
            connection.rollback()
