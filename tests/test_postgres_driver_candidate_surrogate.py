from __future__ import annotations

import pytest

from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS,
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
)


def test_candidate_rejects_isolated_surrogate_with_domain_error() -> None:
    """Malformed Unicode metadata must stay inside the candidate-evidence boundary."""
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="package name"):
        PostgresDriverCandidateEvidence(
            package_name="candidate\ud800driver",
            package_version="1.2.3",
            license_spdx="BSD-3-Clause",
            license_report_sha256="d" * 64,
            python_versions=tuple(sorted(REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS)),
            source_commit_sha="a" * 40,
            artifact_sha256="b" * 64,
            vulnerability_report_sha256="c" * 64,
            known_vulnerability_ids=(),
            capabilities=frozenset(REQUIRED_POSTGRES_DRIVER_CAPABILITIES),
        )
