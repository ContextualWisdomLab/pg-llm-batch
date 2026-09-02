# SPDX-License-Identifier: Apache-2.0
"""Distribution-name normalization contracts for Context Fabric release continuity."""

from __future__ import annotations

from dataclasses import replace

from pg_llm_batch.context_contract_candidate import (
    ContextContractCandidatePin,
    ContextContractCandidateVerification,
    require_context_contract_candidate_compatibility,
    require_context_contract_candidate_release_identity,
)
from pg_llm_batch.context_contract_release import (
    ContextContractReleaseApproval,
    ContextContractReleasePin,
    ContextContractReleaseTransitionVerification,
    ContextContractReleaseVerification,
    require_context_contract_release_compatibility,
    require_context_contract_release_ready,
    require_context_contract_release_transition_ready,
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


def _candidate_pin(
    *,
    distribution_name: str = "cwl-context-contracts",
) -> ContextContractCandidatePin:
    """Build one unreleased candidate identity for normalized-name comparisons."""
    release = _release_pin(distribution_name=distribution_name)
    return ContextContractCandidatePin(
        distribution_name=distribution_name,
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


def test_candidate_expectation_uses_normalized_distribution_identity() -> None:
    """Do not reject one candidate solely for equivalent project-name spelling."""
    candidate = _candidate_pin(distribution_name="CWL.Context__Contracts")
    expected = replace(candidate, distribution_name="cwl-context-contracts")
    verification = ContextContractCandidateVerification(
        candidate_pin=candidate,
        artifact_verified=True,
        conformance_passed=True,
        admission_passed=True,
        provenance_verified=True,
    )

    matched = require_context_contract_candidate_compatibility(
        verification=verification,
        expected=expected,
    )

    assert matched == candidate
    assert matched is not candidate


def test_candidate_release_continuity_uses_normalized_distribution_identity() -> None:
    """Treat PyPA-equivalent project names as one distribution during comparison."""
    release = _release_pin()
    candidate = _candidate_pin(distribution_name="CWL.Context__Contracts")
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


def test_release_policy_binding_uses_normalized_distribution_identity() -> None:
    """Policy approval binds one project identity despite equivalent name spelling."""
    observed_pin = _release_pin(distribution_name="CWL.Context__Contracts")
    approved_pin = replace(observed_pin, distribution_name="cwl-context-contracts")
    observed = ContextContractReleaseVerification(
        release_pin=observed_pin,
        release_published=True,
        artifact_verified=True,
        conformance_passed=True,
        admission_passed=True,
        provenance_verified=True,
    )
    approval = ContextContractReleaseApproval(
        verification=replace(observed, release_pin=approved_pin),
        approval_policy_sha256="9" * 64,
    )

    admitted = require_context_contract_release_ready(
        verification=observed,
        approved=approval,
        required_approval_policy_sha256="9" * 64,
    )

    assert admitted == observed_pin


def test_release_transition_binding_uses_normalized_distribution_identity() -> None:
    """Bind migration evidence by canonical project identity, not raw spelling."""
    current = _release_pin(distribution_name="CWL.Context__Contracts")
    target = replace(
        current,
        release_version="0.2.0",
        source_commit="2" * 40,
        distribution_sha256="3" * 64,
        profile_sha256="4" * 64,
        resource_sha256="5" * 64,
        conformance_sha256="6" * 64,
        admission_sha256="7" * 64,
        provenance_sha256="8" * 64,
    )
    verification = ContextContractReleaseVerification(
        release_pin=target,
        release_published=True,
        artifact_verified=True,
        conformance_passed=True,
        admission_passed=True,
        provenance_verified=True,
    )
    approval = ContextContractReleaseApproval(
        verification=verification,
        approval_policy_sha256="9" * 64,
    )
    transition = ContextContractReleaseTransitionVerification(
        source_release_pin=replace(
            current,
            distribution_name="cwl-context-contracts",
        ),
        target_release_pin=replace(
            target,
            distribution_name="cwl-context-contracts",
        ),
        migration_evidence_sha256="a" * 64,
        rollback_evidence_sha256="b" * 64,
        migration_verified=True,
        rollback_verified=True,
    )

    admitted = require_context_contract_release_transition_ready(
        current_release=current,
        verification=verification,
        approved=approval,
        required_approval_policy_sha256="9" * 64,
        transition=transition,
    )

    assert admitted == target
