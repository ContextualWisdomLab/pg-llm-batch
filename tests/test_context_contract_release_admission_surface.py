# SPDX-License-Identifier: Apache-2.0
"""Public-authority contracts for Context Fabric release admission."""

from __future__ import annotations

import pg_llm_batch.context_contract_release as release_contract


def test_release_pin_identity_match_is_not_public_admission_authority() -> None:
    """A pair of release pins alone must not expose a production admission API."""
    assert not hasattr(
        release_contract,
        "require_context_contract_release_compatibility",
    )
