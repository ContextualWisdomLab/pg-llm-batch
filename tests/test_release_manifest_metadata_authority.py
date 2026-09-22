# SPDX-License-Identifier: Apache-2.0
"""Regression tests for exact primitive release-manifest metadata authority."""

from pathlib import Path

import pytest

from pg_llm_batch import release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


class _StringSubclass(str):
    """Represent caller-owned behavior-capable text that must not become evidence authority."""


@pytest.mark.parametrize(
    ("field_name", "untrusted_value"),
    (
        ("distribution_name", _StringSubclass("pg_llm_batch")),
        ("version", _StringSubclass("0.1.0")),
        ("source_commit", _StringSubclass("a" * 40)),
    ),
)
def test_release_verifier_rejects_string_subclass_metadata_before_artifact_io(
    field_name: str,
    untrusted_value: _StringSubclass,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject behavior-bearing metadata before it can reach artifact verification."""
    monkeypatch.setattr(release_evidence, "_secure_artifact_reads_supported", lambda: True)

    def unexpected_artifact_read(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("untrusted release metadata reached artifact verification")

    monkeypatch.setattr(release_evidence, "_artifact_records", unexpected_artifact_read)

    metadata: dict[str, object] = {
        "distribution_name": "pg_llm_batch",
        "version": "0.1.0",
        "source_commit": "a" * 40,
    }
    metadata[field_name] = untrusted_value

    with pytest.raises(ReleaseEvidenceError, match="invalid release evidence metadata"):
        verify_reproducible_release(
            Path("first"),
            Path("second"),
            distribution_name=metadata["distribution_name"],  # type: ignore[arg-type]
            version=metadata["version"],  # type: ignore[arg-type]
            source_commit=metadata["source_commit"],  # type: ignore[arg-type]
            source_date_epoch=1,
        )
