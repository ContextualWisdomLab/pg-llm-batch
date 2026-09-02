# SPDX-License-Identifier: Apache-2.0
"""Distribution-name normalization contracts for Context Fabric release continuity."""

from __future__ import annotations

from dataclasses import replace

from pg_llm_batch.context_contract_candidate import (
    ContextContractCandidatePin,
    ContextContractCandidateVerification,
    require_context_contract_candidate_release_identity,
)
from pg_llm_batch.context_contract_release import (
    ContextContractReleasePin,
    require_context_contract_release_compatibility,
)


def _release_pin(*, distribution_name: str = "cwl-context-contracts") -> ContextContractReleasePin:
    """Build one immutable release identity for normalized-name comparisons."""
    return ContextContractReleasePin(
        distribution_name=distribution_name,
        release_version="0.1.0",
        source_commit="a" * 40,
        distribution_sha256="b" * 64,
        profile_name="context-assertion-event-semantics.v1.json",
        profile_sha256="c" * 64,
        resource_name="context-assertion.schema.json",
        resource_sha256="d" * 64,
        conformance_sha256="e" * 64,
        admission_sha256="f" * 64,
        provenance_sha256="1" * 64,
    )


def test_candidate_release_continuity_uses_normalized_distribution_identity() -> None:
    """Treat PyPA-equivalent project names as one distribution during comparison."""
    release = _release_pin()
    candidate = ContextContractCandidatePin(
        distribution_name="CWL.Context__Contracts",
        source_commit=release.source_commit,
        candidate_artifact_sha256=release.distribution_sha256,
        profile_name=release.profile_name,
        profile_sha256=release.profile_sha256,
        resource_name=release.resource_name,
        resource_sha256=release.resource_sha256,
        conformance_sha256=release.conformance_sha256,
        admission_sha256=release.admission_sha256,
        provenance_sha256=release.provenance_sha256,
    )
    verification = ContextContractCandidateVerification(
        candidate_pin=candidate,
        artifact_verified=True,
        conformance_passed=True,
        admission_passed=True,
        provenance_verified=True,
    )

    matched = require_context_contract_candidate_release_identity(
        verification=verification,
        release=release,
    )

    assert matched == candidate


def test_release_approval_compatibility_uses_normalized_distribution_identity() -> None:
    """Do not reject an approved release solely for equivalent project-name spelling."""
    candidate = _release_pin(distribution_name="CWL.Context__Contracts")
    approved = replace(candidate, distribution_name="cwl-context-contracts")

    admitted = require_context_contract_release_compatibility(
        candidate=candidate,
        approved=approved,
    )

    assert admitted == candidate
    assert admitted is not candidate
