# SPDX-License-Identifier: Apache-2.0
"""Regression contract for canonical compressed wheel compatibility-tag sets."""

from pathlib import Path

import pytest

from pg_llm_batch import release_evidence
from pg_llm_batch.release_evidence import (
    ReleaseEvidenceError,
    verify_reproducible_release,
)


def _write_release_with_python_tag(directory: Path, python_tag: str) -> None:
    directory.mkdir()
    (directory / "pg_llm_batch-0.1.0.tar.gz").write_bytes(b"sdist")
    (directory / f"pg_llm_batch-0.1.0-{python_tag}-none-any.whl").write_bytes(b"wheel")


@pytest.mark.parametrize("python_tag", ("py3.py2", "py3.py3"))
def test_release_verifier_rejects_noncanonical_compressed_python_tag_set_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    python_tag: str,
) -> None:
    """Reject unsorted or duplicate compressed Python tags before wheel hashing."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release_with_python_tag(first, python_tag)
    _write_release_with_python_tag(second, python_tag)

    def artifact_record_guard(
        _directory_descriptor: int,
        name: str,
        _expected_identity: object,
    ) -> dict[str, object]:
        if name.endswith(".whl"):
            raise AssertionError(
                "wheel with noncanonical compressed Python tags reached artifact hashing"
            )
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
