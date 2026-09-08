# SPDX-License-Identifier: Apache-2.0
"""Regression contract for lifecycle-outbox UUID default authority."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


def test_outbox_migration_converges_uuid_default_to_core_postgres_generator() -> None:
    """Durable UUID creation must not depend on a mutable public helper function."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")

    assert (
        "context_outbox_uuid UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid()"
        in migration
    )
    assert (
        "ALTER COLUMN context_outbox_uuid SET DEFAULT pg_catalog.gen_random_uuid()"
        in migration
    )
    assert "lifecycle outbox UUID default failed canonical verification" in migration
