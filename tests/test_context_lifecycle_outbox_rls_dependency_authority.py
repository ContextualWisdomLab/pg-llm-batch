# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox RLS dependency authority."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


def test_canonical_rls_policy_checks_function_and_operator_dependency_authority() -> None:
    """Admission must supplement deparsed policy text with tracked dependency OIDs."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")

    dependency_guard = "FROM pg_catalog.pg_depend AS unexpected_policy_dependency"
    assert migration.count(dependency_guard) == 2
    assert migration.count(
        "'pg_catalog.current_setting(pg_catalog.text,pg_catalog.bool)'::pg_catalog.regprocedure"
    ) == 2
    assert migration.count(
        "'pg_catalog.=(pg_catalog.text,pg_catalog.text)'::pg_catalog.regoperator"
    ) == 2
    assert migration.count(
        "unexpected_policy_dependency.deptype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'n'"
    ) == 2
