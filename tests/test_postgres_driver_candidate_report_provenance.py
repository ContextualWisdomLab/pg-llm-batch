from __future__ import annotations

from dataclasses import fields

import pytest

from pg_llm_batch.postgres_driver_candidate import (
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
)


def test_candidate_evidence_has_explicit_schema_version() -> None:
    """Acquisition receipts need a versioned schema before their meaning can evolve."""
    evidence_fields = {field.name for field in fields(PostgresDriverCandidateEvidence)}

    assert "evidence_schema_version" in evidence_fields


def test_candidate_evidence_binds_capability_report_identity() -> None:
    """Capability claims need immutable report identity before parity admission."""
    evidence_fields = {field.name for field in fields(PostgresDriverCandidateEvidence)}

    assert "capability_report_sha256" in evidence_fields


def test_candidate_schema_version_rejects_equality_spoofing() -> None:
    """Untrusted receipt objects cannot impersonate the current schema by equality."""

    class PretendsToBeCurrent:
        def __eq__(self, other: object) -> bool:
            return True

    with pytest.raises(PostgresDriverCandidateEvidenceError, match="schema version"):
        PostgresDriverCandidateEvidence(
            package_name="candidate-driver",
            package_version="1.2.3",
            license_spdx="BSD-3-Clause",
            license_report_sha256="d" * 64,
            python_versions=("3.10", "3.11", "3.12", "3.13", "3.14"),
            source_commit_sha="a" * 40,
            artifact_sha256="b" * 64,
            vulnerability_report_sha256="c" * 64,
            known_vulnerability_ids=(),
            capabilities=frozenset({"parameterized_sql"}),
            evidence_schema_version=PretendsToBeCurrent(),  # type: ignore[arg-type]
        )
