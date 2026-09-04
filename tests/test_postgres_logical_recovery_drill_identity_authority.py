# SPDX-License-Identifier: Apache-2.0
"""Regression contract for logical recovery drill identity authority."""

from dataclasses import fields

from pg_llm_batch.postgres_logical_recovery_drill import PostgresLogicalRecoveryDrillEvidence


def test_logical_recovery_drill_labels_restore_identity_as_caller_asserted() -> None:
    """Require evidence to distinguish caller assertion from package observation."""
    field_names = {field.name for field in fields(PostgresLogicalRecoveryDrillEvidence)}

    assert "caller_asserted_restore_system_identifier" in field_names
    assert "restore_system_identifier" not in field_names
