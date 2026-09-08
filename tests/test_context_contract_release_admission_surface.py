# SPDX-License-Identifier: Apache-2.0
"""Release-identity authority regressions for Context Fabric admission."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.context_contract_release import (
    ContextContractReleasePin,
    ContextContractReleasePinError,
    ContextContractReleaseTransitionVerification,
    validate_context_contract_release_transition_verification,
)


SOURCE_PIN = ContextContractReleasePin(
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


def _equivocated_target(**changes: str) -> ContextContractReleasePin:
    """Return a same-version target whose immutable release identity has drifted."""
    defaults = {
        "source_commit": "2" * 40,
        "distribution_sha256": "3" * 64,
        "profile_sha256": "4" * 64,
        "resource_sha256": "5" * 64,
        "conformance_sha256": "6" * 64,
        "admission_sha256": "7" * 64,
        "provenance_sha256": "8" * 64,
    }
    defaults.update(changes)
    return replace(SOURCE_PIN, **defaults)


def _transition(target: ContextContractReleasePin) -> ContextContractReleaseTransitionVerification:
    """Bind positive migration evidence to one candidate target release identity."""
    return ContextContractReleaseTransitionVerification(
        source_release_pin=SOURCE_PIN,
        target_release_pin=target,
        migration_evidence_sha256="9" * 64,
        rollback_evidence_sha256="a" * 64,
        migration_verified=True,
        rollback_verified=True,
    )


def test_release_transition_rejects_same_version_with_different_immutable_content() -> None:
    """One distribution version cannot identify two different immutable releases."""
    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_transition_verification(
            _transition(_equivocated_target())
        )


def test_release_transition_rejects_normalized_distribution_alias_equivocation() -> None:
    """Python distribution spelling aliases cannot bypass immutable version identity."""
    alias_target = _equivocated_target(
        distribution_name="future_context.contract_package"
    )

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_transition_verification(
            _transition(alias_target)
        )
