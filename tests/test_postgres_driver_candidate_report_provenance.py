from __future__ import annotations

from dataclasses import fields

from pg_llm_batch.postgres_driver_candidate import PostgresDriverCandidateEvidence


def test_candidate_binds_python_and_capability_reports_to_immutable_digests() -> None:
    """Parity claims need immutable report identities, not self-asserted value sets."""
    evidence_fields = {field.name for field in fields(PostgresDriverCandidateEvidence)}

    assert "python_report_sha256" in evidence_fields
    assert "capability_report_sha256" in evidence_fields
