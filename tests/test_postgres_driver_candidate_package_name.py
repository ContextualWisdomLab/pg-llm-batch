from __future__ import annotations

import pytest

from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS,
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
)


@pytest.mark.parametrize(
    "package_name",
    [
        ".candidate-driver",
        "candidate-driver-",
        "candidate/driver",
        "candidate@driver",
        "candidaté-driver",
    ],
)
def test_candidate_rejects_non_pypa_distribution_names(package_name: str) -> None:
    """Supply-chain evidence must use a valid Python distribution project name."""
    with pytest.raises(PostgresDriverCandidateEvidenceError, match="package name"):
        PostgresDriverCandidateEvidence(
            package_name=package_name,
            package_version="1.2.3",
            license_spdx="BSD-3-Clause",
            license_report_sha256="d" * 64,
            python_versions=tuple(sorted(REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS)),
            source_commit_sha="a" * 40,
            artifact_sha256="b" * 64,
            vulnerability_report_sha256="c" * 64,
            capability_report_sha256="e" * 64,
            known_vulnerability_ids=(),
            capabilities=frozenset(REQUIRED_POSTGRES_DRIVER_CAPABILITIES),
        )
