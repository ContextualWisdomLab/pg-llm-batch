# SPDX-License-Identifier: Apache-2.0
"""Regression tests for canonical release-manifest generation bounds."""

from pathlib import Path

import pytest

from pg_llm_batch import release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


def _write_matching_release_artifacts(directory: Path) -> None:
    directory.mkdir()
    (directory / "pg_llm_batch-0.1.0.tar.gz").write_bytes(b"sdist")
    (directory / "pg_llm_batch-0.1.0-py3-none-any.whl").write_bytes(b"wheel")


def test_release_verifier_rejects_json_unsafe_source_date_epoch(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_matching_release_artifacts(first)
    _write_matching_release_artifacts(second)

    with pytest.raises(ReleaseEvidenceError, match="invalid release evidence metadata"):
        verify_reproducible_release(
            first,
            second,
            distribution_name="pg_llm_batch",
            version="0.1.0",
            source_commit="a" * 40,
            source_date_epoch=1 << 53,
        )


def test_release_verifier_rejects_json_unsafe_artifact_size_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an oversized artifact from trusted stat metadata before reading bytes."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_matching_release_artifacts(first)
    _write_matching_release_artifacts(second)

    monkeypatch.setattr(release_evidence, "_MAX_INTEROPERABLE_JSON_INTEGER", 4)

    def unexpected_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("oversized release artifact was hashed before size admission")

    monkeypatch.setattr(release_evidence.os, "read", unexpected_read)

    with pytest.raises(ReleaseEvidenceError, match="canonical JSON size limit"):
        verify_reproducible_release(
            first,
            second,
            distribution_name="pg_llm_batch",
            version="0.1.0",
            source_commit="a" * 40,
            source_date_epoch=1,
        )
