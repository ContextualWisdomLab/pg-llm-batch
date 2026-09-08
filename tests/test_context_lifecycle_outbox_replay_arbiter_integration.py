# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL verification for lifecycle-outbox replay-key convergence."""

from __future__ import annotations

import os

import pytest

from pg_llm_batch.context_lifecycle_outbox import (
    apply_context_lifecycle_outbox_schema,
)


pytestmark = pytest.mark.integration
_DSN = os.environ.get("PG_LLM_BATCH_TEST_DSN")
_SKIP_NO_DB = pytest.mark.skipif(
    not _DSN,
    reason="PG_LLM_BATCH_TEST_DSN not set; skipping live-DB integration",
)
_CONSTRAINT = "uq_llm_context_lifecycle_outbox_tenant_evidence"
_CANONICAL_CATALOG = ("u", True, False, True)


def _replay_arbiter_catalog(
    dsn: str,
) -> tuple[str, bool, bool, bool] | None:
    """Read the exact catalog identity required by runtime ON CONFLICT inference."""
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT contype,
                       convalidated,
                       condeferrable,
                       conkey = ARRAY[
                           (SELECT attnum::smallint
                            FROM pg_attribute
                            WHERE attrelid =
                                  'public.llm_context_lifecycle_outbox'::regclass
                              AND attname = 'tenant_scope'
                              AND NOT attisdropped),
                           (SELECT attnum::smallint
                            FROM pg_attribute
                            WHERE attrelid =
                                  'public.llm_context_lifecycle_outbox'::regclass
                              AND attname = 'evidence_id'
                              AND NOT attisdropped)
                       ]
                FROM pg_constraint
                WHERE conrelid = 'public.llm_context_lifecycle_outbox'::regclass
                  AND conname = %s
                """,
                (_CONSTRAINT,),
            )
            return cursor.fetchone()


def _install_noncanonical_replay_arbiter(dsn: str) -> None:
    """Install a same-name deferrable/wrong-order UNIQUE for repair verification."""
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE public.llm_context_lifecycle_outbox "
                f"DROP CONSTRAINT {_CONSTRAINT}"
            )
            cursor.execute(
                f"ALTER TABLE public.llm_context_lifecycle_outbox "
                f"ADD CONSTRAINT {_CONSTRAINT} "
                "UNIQUE (evidence_id, tenant_scope) DEFERRABLE INITIALLY IMMEDIATE"
            )
        connection.commit()


def _restore_canonical_replay_arbiter(dsn: str) -> None:
    """Restore the canonical replay constraint so a failed test cannot poison CI."""
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE public.llm_context_lifecycle_outbox "
                f"DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
            )
            cursor.execute(
                f"ALTER TABLE public.llm_context_lifecycle_outbox "
                f"ADD CONSTRAINT {_CONSTRAINT} UNIQUE (tenant_scope, evidence_id)"
            )
        connection.commit()


def _rebuild_canonical_outbox(dsn: str) -> None:
    """Rebuild the isolated test table after physical row-shape sabotage."""
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE public.llm_context_lifecycle_outbox")
        connection.commit()
    apply_context_lifecycle_outbox_schema(dsn)


@_SKIP_NO_DB
def test_live_migration_repairs_missing_and_noncanonical_replay_arbiter() -> None:
    """Migration 0008 must converge stale tables to one usable UPSERT arbiter."""
    assert _DSN is not None
    import psycopg

    apply_context_lifecycle_outbox_schema(_DSN)
    try:
        with psycopg.connect(_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"ALTER TABLE public.llm_context_lifecycle_outbox "
                    f"DROP CONSTRAINT {_CONSTRAINT}"
                )
            connection.commit()

        apply_context_lifecycle_outbox_schema(_DSN)
        assert _replay_arbiter_catalog(_DSN) == _CANONICAL_CATALOG

        _install_noncanonical_replay_arbiter(_DSN)
        apply_context_lifecycle_outbox_schema(_DSN)
        assert _replay_arbiter_catalog(_DSN) == _CANONICAL_CATALOG

        # A current canonical catalog state must remain safely re-applicable.
        apply_context_lifecycle_outbox_schema(_DSN)
        assert _replay_arbiter_catalog(_DSN) == _CANONICAL_CATALOG
    finally:
        if _replay_arbiter_catalog(_DSN) != _CANONICAL_CATALOG:
            _restore_canonical_replay_arbiter(_DSN)


@_SKIP_NO_DB
def test_live_migration_rejects_unexpected_outbox_columns() -> None:
    """Additive and dropped physical columns must both remain fail-closed."""
    assert _DSN is not None
    import psycopg

    apply_context_lifecycle_outbox_schema(_DSN)
    with psycopg.connect(_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE public.llm_context_lifecycle_outbox "
                "ADD COLUMN undeclared_payload text"
            )
        connection.commit()

    try:
        with pytest.raises(psycopg.Error, match="structural schema mismatch"):
            apply_context_lifecycle_outbox_schema(_DSN)

        with psycopg.connect(_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE public.llm_context_lifecycle_outbox "
                    "DROP COLUMN undeclared_payload"
                )
            connection.commit()

        # PostgreSQL keeps an attisdropped catalog/physical slot after DROP COLUMN.
        # The migration intentionally requires operator-controlled rebuild instead
        # of treating that state as equivalent to a table that never held the data.
        with pytest.raises(psycopg.Error, match="structural schema mismatch"):
            apply_context_lifecycle_outbox_schema(_DSN)
    finally:
        _rebuild_canonical_outbox(_DSN)
