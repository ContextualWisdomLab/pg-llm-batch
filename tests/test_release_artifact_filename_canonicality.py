# SPDX-License-Identifier: Apache-2.0
"""Regression contract for canonical release artifact filenames."""

from pathlib import Path

import pytest

from pg_llm_batch import release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


def _write_release_with_noncanonical_sdist(directory: Path) -> None:
    directory.mkdir()
    (directory / "pg-llm-batch-0.1.0.tar.gz").write_bytes(b"sdist")
    (directory / "pg_llm_batch-0.1.0-py3-none-any.whl").write_bytes(b"wheel")


def test_release_verifier_rejects_noncanonical_normalized_sdist_name_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require the standardized normalized sdist name before artifact reads."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release_with_noncanonical_sdist(first)
    _write_release_with_noncanonical_sdist(second)

    def unexpected_artifact_read(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("noncanonical sdist reached artifact hashing")

    monkeypatch.setattr(release_evidence, "_artifact_record", unexpected_artifact_read)

    with pytest.raises(ReleaseEvidenceError, match="distribution and version"):
        verify_reproducible_release(
            first,
            second,
            distribution_name="pg-llm-batch",
            version="0.1.0",
            source_commit="a" * 40,
            source_date_epoch=1,
        )
