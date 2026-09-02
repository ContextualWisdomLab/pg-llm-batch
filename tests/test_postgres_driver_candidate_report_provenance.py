from __future__ import annotations

from dataclasses import fields

from pg_llm_batch.postgres_driver_candidate import PostgresDriverCandidateEvidence


def test_candidate_evidence_has_explicit_schema_version() -> None:
    """Acquisition receipts need a versioned schema before their meaning can evolve."""
    evidence_fields = {field.name for field in fields(PostgresDriverCandidateEvidence)}

    assert "evidence_schema_version" in evidence_fields
