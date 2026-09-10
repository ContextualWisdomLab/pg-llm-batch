"""Capability-shape regressions for PostgreSQL driver candidate evidence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS,
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
)


class _StringSubclass(str):
    """Represent a shaped string that must not enter supply-chain evidence."""


def _valid_evidence() -> PostgresDriverCandidateEvidence:
    """Build one exact primitive candidate receipt for shape-validation tests."""
    return PostgresDriverCandidateEvidence(
        package_name="pg8000",
        package_version="1.31.5",
        license_spdx="BSD-3-Clause",
        license_report_sha256="1" * 64,
        python_versions=tuple(sorted(REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS)),
        source_commit_sha="2" * 40,
        artifact_sha256="3" * 64,
        vulnerability_report_sha256="4" * 64,
        capability_report_sha256="5" * 64,
        known_vulnerability_ids=(),
        capabilities=REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    )


def test_candidate_rejects_string_subclass_capability_before_set_comparison() -> None:
    """Supply-chain capability evidence must contain exact built-in strings only."""
    capabilities = set(REQUIRED_POSTGRES_DRIVER_CAPABILITIES)
    capabilities.remove("jsonb")
    capabilities.add(_StringSubclass("jsonb"))

    with pytest.raises(
        PostgresDriverCandidateEvidenceError,
        match="PostgreSQL driver capability evidence is invalid",
    ):
        replace(_valid_evidence(), capabilities=frozenset(capabilities))
