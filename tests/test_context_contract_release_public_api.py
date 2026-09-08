# SPDX-License-Identifier: Apache-2.0
"""Public API contract for immutable Context Fabric release admission."""

from __future__ import annotations

import pg_llm_batch
import pg_llm_batch.context_contract_manifest as contract_manifest
import pg_llm_batch.context_contract_release as contract_release


def test_context_contract_release_admission_is_available_from_package_root() -> None:
    """Hosts should not depend on implementation-module paths for release admission."""
    expected = {
        "ContextContractReleaseApproval": contract_release.ContextContractReleaseApproval,
        "ContextContractReleaseManifestError": contract_manifest.ContextContractReleaseManifestError,
        "ContextContractReleasePin": contract_release.ContextContractReleasePin,
        "ContextContractReleasePinError": contract_release.ContextContractReleasePinError,
        "ContextContractReleaseTransitionVerification": (
            contract_release.ContextContractReleaseTransitionVerification
        ),
        "ContextContractReleaseVerification": (
            contract_release.ContextContractReleaseVerification
        ),
        "require_context_contract_release_ready": (
            contract_release.require_context_contract_release_ready
        ),
        "require_context_contract_release_transition_ready": (
            contract_release.require_context_contract_release_transition_ready
        ),
        "resolve_context_contract_release_manifest": (
            contract_manifest.resolve_context_contract_release_manifest
        ),
    }
    for symbol_name, implementation in expected.items():
        assert getattr(pg_llm_batch, symbol_name) is implementation
        assert symbol_name in pg_llm_batch.__all__
