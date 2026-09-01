# SPDX-License-Identifier: Apache-2.0
"""Policy-authority contracts for optional Context Fabric release admission."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.context_contract_release import (
    ContextContractReleaseApproval,
    ContextContractReleasePin,
    ContextContractReleasePinError,
    ContextContractReleaseVerification,
    require_context_contract_release_ready,
)


RELEASE_PIN = ContextContractReleasePin(
    distribution_name="future-context-contract-package",
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
VERIFICATION = ContextContractReleaseVerification(
    release_pin=RELEASE_PIN,
    release_published=True,
    conformance_passed=True,
    admission_passed=True,
    provenance_verified=True,
)
APPROVAL = ContextContractReleaseApproval(
    verification=VERIFICATION,
    approval_policy_sha256="2" * 64,
)
REQUIRED_POLICY_SHA256 = "2" * 64


def test_release_readiness_requires_distinct_policy_approval_evidence() -> None:
    """Observed gate evidence cannot impersonate deployment-policy approval."""
    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=VERIFICATION,
            approved=VERIFICATION,  # type: ignore[arg-type]
            required_approval_policy_sha256=REQUIRED_POLICY_SHA256,
        )


def test_release_readiness_accepts_policy_bound_exact_verification() -> None:
    """Policy approval binds its identity to the exact verified release receipt."""
    admitted = require_context_contract_release_ready(
        verification=VERIFICATION,
        approved=APPROVAL,
        required_approval_policy_sha256=REQUIRED_POLICY_SHA256,
    )

    assert admitted == RELEASE_PIN
    assert admitted is not RELEASE_PIN


def test_release_readiness_rejects_malformed_policy_identity() -> None:
    """Deployment-policy provenance must be an exact bounded SHA-256 identity."""
    approval = replace(APPROVAL, approval_policy_sha256="operator-secret")

    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_ready(
            verification=VERIFICATION,
            approved=approval,
            required_approval_policy_sha256=REQUIRED_POLICY_SHA256,
        )

    assert str(raised.value) == "invalid release pin"
    assert "operator-secret" not in str(raised.value)


def test_release_readiness_rejects_deleted_policy_identity() -> None:
    """Deleted approval provenance fails through the bounded policy boundary."""
    approval = replace(APPROVAL)
    object.__delattr__(approval, "approval_policy_sha256")

    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_ready(
            verification=VERIFICATION,
            approved=approval,
            required_approval_policy_sha256=REQUIRED_POLICY_SHA256,
        )

    assert str(raised.value) == "invalid release pin"


def test_release_readiness_rejects_policy_approval_for_other_verification() -> None:
    """An approval for another immutable release cannot authorize this observation."""
    other_verification = replace(
        VERIFICATION,
        release_pin=replace(RELEASE_PIN, release_version="0.1.1"),
    )
    approval = replace(APPROVAL, verification=other_verification)

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=VERIFICATION,
            approved=approval,
            required_approval_policy_sha256=REQUIRED_POLICY_SHA256,
        )


def test_release_readiness_rejects_unapproved_deployment_policy_identity() -> None:
    """A well-formed but unapproved policy digest cannot authorize deployment."""
    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=VERIFICATION,
            approved=APPROVAL,
            required_approval_policy_sha256="3" * 64,
        )


def test_release_readiness_rejects_malformed_required_policy_identity() -> None:
    """Configured policy identity is validated without reflecting hostile values."""
    with pytest.raises(ContextContractReleasePinError) as raised:
        require_context_contract_release_ready(
            verification=VERIFICATION,
            approved=APPROVAL,
            required_approval_policy_sha256="operator-secret",
        )

    assert str(raised.value) == "invalid release pin"
    assert "operator-secret" not in str(raised.value)
