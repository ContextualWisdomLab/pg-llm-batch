# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox RLS expression authority."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_POLICY_DEPENDENCY_GUARD = """          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend AS policy_depend
              WHERE policy_depend.classid = 'pg_policy'::regclass
                AND policy_depend.objid = pg_policy.oid
                AND policy_depend.refclassid IN (
                    'pg_proc'::regclass,
                    'pg_operator'::regclass
                )
          )"""


def test_canonical_rls_policy_rejects_noncatalog_expression_dependencies() -> None:
    """Text-identical policy expressions must not admit shadow functions/operators."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")

    assert migration.count(_POLICY_DEPENDENCY_GUARD) == 2
    assert migration.count("OPERATOR(pg_catalog.=)") == 2
    assert migration.count(
        "pg_catalog.current_setting('pg_llm_batch.tenant_scope', true)"
    ) == 2
