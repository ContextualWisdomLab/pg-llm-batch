# SPDX-License-Identifier: Apache-2.0
"""Coverage contract for release artifact size admission."""

from pathlib import Path

import pytest

from pg_llm_batch import release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


def _write_release(directory: Path) -> None:
    directory.mkdir()
    (directory / "pg_llm_batch-0.1.0.tar.gz").write_bytes(b"sdist")
    (directory / "pg_llm_batch-0.1.0-py3-none-any.whl").write_bytes(b"wheel")


def test_release_verifier_rejects_artifact_size_above_canonical_json_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover the production size rejection on ordinary regular artifacts."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    monkeypatch.setattr(release_evidence, "_MAX_INTEROPERABLE_JSON_INTEGER", 4)

    with pytest.raises(ReleaseEvidenceError, match="canonical JSON size limit"):
        verify_reproducible_release(
            first,
            second,
            distribution_name="pg-llm-batch",
            version="0.1.0",
            source_commit="a" * 40,
            source_date_epoch=1,
        )
