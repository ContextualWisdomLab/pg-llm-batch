# SPDX-License-Identifier: Apache-2.0
"""Cover built-in durable row shapes admitted by the lifecycle outbox."""

from pg_llm_batch.context_lifecycle_evidence import ContextLifecycleEvidenceSeed
from pg_llm_batch.context_lifecycle_outbox import _evidence_from_row


def test_builtin_list_row_is_snapshotted_before_validation() -> None:
    """A plain list returned by an adapter remains a supported inert row shape."""
    seed = ContextLifecycleEvidenceSeed(
        evidence_id="event-list-row",
        event_type="batch.lifecycle.observed",
        tenant_scope_sha256="a" * 64,
        subject_ref_sha256="b" * 64,
        authority_ref_sha256="c" * 64,
        origin_ref_sha256="d" * 64,
        truth_status="observed",
        valid_time="2026-09-04T21:00:00Z",
        system_time="2026-09-04T21:00:01Z",
        provenance_ref_sha256="e" * 64,
        evidence_ref_sha256="f" * 64,
    )
    row = [
        seed.evidence_id,
        seed.event_type,
        seed.tenant_scope_sha256,
        seed.subject_ref_sha256,
        seed.authority_ref_sha256,
        seed.origin_ref_sha256,
        seed.truth_status,
        seed.valid_time,
        seed.system_time,
        seed.provenance_ref_sha256,
        seed.evidence_ref_sha256,
    ]

    assert _evidence_from_row(row) == seed
