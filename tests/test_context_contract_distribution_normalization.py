# SPDX-License-Identifier: Apache-2.0
"""Distribution-name normalization contracts for Context Fabric release continuity."""

from __future__ import annotations

from pg_llm_batch.context_contract_candidate import (
    ContextContractCandidatePin,
    ContextContractCandidateVerification,
    require_context_contract_candidate_release_identity,
)
from pg_llm_batch.context_contract_release import ContextContractReleasePin


def test_candidate_release_continuity_uses_normalized_distribution_identity() -> None:
    """Treat PyPA-equivalent project names as one distribution during comparison."""
    candidate = ContextContractCandidatePin(
        distribution_name="CWL.Context__Contracts",
        source_commit="a" * 40,
        candidate_artifact_sha256="b" * 64,
        profile_name="context-assertion-event-semantics.v1.json",
        profile_sha256="c" * 64,
        resource_name="context-assertion.schema.json",
        resource_sha256="d" * 64,
        conformance_sha256="e" * 64,
        admission_sha256="f" * 64,
        provenance_sha256="1" * 64,
    )
    verification = ContextContractCandidateVerification(
        candidate_pin=candidate,
        artifact_verified=True,
        conformance_passed=True,
        admission_passed=True,
        provenance_verified=True,
    )
    release = ContextContractReleasePin(
        distribution_name="cwl-context-contracts",
        release_version="0.1.0",
        source_commit=candidate.source_commit,
        distribution_sha256=candidate.candidate_artifact_sha256,
        profile_name=candidate.profile_name,
        profile_sha256=candidate.profile_sha256,
        resource_name=candidate.resource_name,
        resource_sha256=candidate.resource_sha256,
        conformance_sha256=candidate.conformance_sha256,
        admission_sha256=candidate.admission_sha256,
        provenance_sha256=candidate.provenance_sha256,
    )

    matched = require_context_contract_candidate_release_identity(
        verification=verification,
        release=release,
    )

    assert matched == candidate
