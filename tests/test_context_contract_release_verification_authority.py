# SPDX-License-Identifier: Apache-2.0
"""Authority-bound acceptance contracts for Context Fabric release evidence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.context_contract_release import (
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


def test_release_identity_alone_cannot_authorize_release_readiness() -> None:
    """A pinned identity is not proof that release evidence actually passed."""
    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        require_context_contract_release_ready(
            verification=VERIFICATION,
            approved=RELEASE_PIN,
        )


def test_release_readiness_accepts_only_policy_approved_verification_receipt() -> None:
    """The trusted policy boundary must approve the subject-bound receipt itself."""
    admitted = require_context_contract_release_ready(
        verification=VERIFICATION,
        approved=replace(VERIFICATION),
    )

    assert admitted == RELEASE_PIN
    assert admitted is not RELEASE_PIN
