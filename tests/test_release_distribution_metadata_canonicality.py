# SPDX-License-Identifier: Apache-2.0
"""Regression contract for canonical release-distribution metadata."""

from pathlib import Path

import pytest

from pg_llm_batch import release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


def test_release_verifier_rejects_noncanonical_distribution_before_artifact_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an equivalent but non-normalized project name before artifact verification."""
    monkeypatch.setattr(release_evidence, "_secure_artifact_reads_supported", lambda: True)

    def unexpected_artifact_read(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("noncanonical distribution metadata reached artifact verification")

    monkeypatch.setattr(release_evidence, "_artifact_records", unexpected_artifact_read)

    with pytest.raises(ReleaseEvidenceError, match="invalid release evidence metadata"):
        verify_reproducible_release(
            Path("first"),
            Path("second"),
            distribution_name="PG.LLM_Batch",
            version="0.1.0",
            source_commit="a" * 40,
            source_date_epoch=1,
        )
