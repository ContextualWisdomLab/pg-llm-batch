# SPDX-License-Identifier: Apache-2.0
"""Regression contract for canonical wheel build-tag grammar."""

from pathlib import Path

import pytest

from pg_llm_batch import release_evidence
from pg_llm_batch.release_evidence import (
    ReleaseEvidenceError,
    verify_reproducible_release,
)


def _write_release_with_invalid_build_tag(directory: Path) -> None:
    directory.mkdir()
    (directory / "pg_llm_batch-0.1.0.tar.gz").write_bytes(b"sdist")
    (directory / "pg_llm_batch-0.1.0-build-py3-none-any.whl").write_bytes(b"wheel")


def test_release_verifier_rejects_nondigit_wheel_build_tag_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a wheel build tag that does not begin with a digit before hashing."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release_with_invalid_build_tag(first)
    _write_release_with_invalid_build_tag(second)

    def artifact_record_guard(
        _directory_descriptor: int,
        name: str,
        _expected_identity: object,
    ) -> dict[str, object]:
        if name.endswith(".whl"):
            raise AssertionError("wheel with invalid build tag reached artifact hashing")
        return {"filename": name, "sha256": "0" * 64, "size": 5}

    monkeypatch.setattr(release_evidence, "_artifact_record", artifact_record_guard)

    with pytest.raises(ReleaseEvidenceError, match="distribution and version"):
        verify_reproducible_release(
            first,
            second,
            distribution_name="pg-llm-batch",
            version="0.1.0",
            source_commit="a" * 40,
            source_date_epoch=1,
        )
