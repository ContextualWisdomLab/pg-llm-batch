# SPDX-License-Identifier: Apache-2.0
"""Public package contract for the release-independent lifecycle evidence ACL seam."""

from __future__ import annotations

import pg_llm_batch
from pg_llm_batch.context_lifecycle_evidence import (
    ContextLifecycleEvidenceError,
    ContextLifecycleEvidenceSeed,
    require_context_lifecycle_replay_identity,
    require_context_lifecycle_scope_continuity,
    validate_context_lifecycle_evidence_seed,
)


def test_package_exports_context_lifecycle_evidence_contract() -> None:
    """Consumers should not need to import an implementation submodule directly."""
    assert pg_llm_batch.ContextLifecycleEvidenceError is ContextLifecycleEvidenceError
    assert pg_llm_batch.ContextLifecycleEvidenceSeed is ContextLifecycleEvidenceSeed
    assert (
        pg_llm_batch.validate_context_lifecycle_evidence_seed
        is validate_context_lifecycle_evidence_seed
    )
    assert (
        pg_llm_batch.require_context_lifecycle_replay_identity
        is require_context_lifecycle_replay_identity
    )
    assert (
        pg_llm_batch.require_context_lifecycle_scope_continuity
        is require_context_lifecycle_scope_continuity
    )
