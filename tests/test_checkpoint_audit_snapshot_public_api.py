# SPDX-License-Identifier: Apache-2.0
"""Public package exports for checkpoint-audit snapshot manifests."""

import pg_llm_batch
from pg_llm_batch import checkpoint_audit


def test_snapshot_manifest_contract_is_exported_from_package_root() -> None:
    """Hosts can import the reviewed snapshot evidence contract from pg_llm_batch."""
    assert (
        pg_llm_batch.CheckpointAuditSnapshotManifest
        is checkpoint_audit.CheckpointAuditSnapshotManifest
    )
    assert (
        pg_llm_batch.MAX_CHECKPOINT_AUDIT_SNAPSHOT_EVENTS
        == checkpoint_audit.MAX_CHECKPOINT_AUDIT_SNAPSHOT_EVENTS
    )
    assert (
        pg_llm_batch.validate_checkpoint_audit_snapshot_max_events
        is checkpoint_audit.validate_checkpoint_audit_snapshot_max_events
    )
