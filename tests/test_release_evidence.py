# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for deterministic release artifact evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pg_llm_batch.release_evidence import (
    ReleaseEvidenceError,
    verify_reproducible_release,
    write_release_manifest,
)


DISTRIBUTION = "pg-llm-batch"
VERSION = "0.1.0"
COMMIT = "a" * 40
SOURCE_DATE_EPOCH = 1_786_000_000
WHEEL = "pg_llm_batch-0.1.0-py3-none-any.whl"
SDIST = "pg_llm_batch-0.1.0.tar.gz"


def _write_release(directory: Path, wheel: bytes = b"wheel", sdist: bytes = b"sdist") -> None:
    directory.mkdir()
    (directory / WHEEL).write_bytes(wheel)
    (directory / SDIST).write_bytes(sdist)


def test_verify_reproducible_release_returns_bounded_deterministic_manifest(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)

    manifest = verify_reproducible_release(
        first,
        second,
        distribution_name=DISTRIBUTION,
        version=VERSION,
        source_commit=COMMIT,
        source_date_epoch=SOURCE_DATE_EPOCH,
    )

    assert manifest == {
        "schema_version": 1,
        "distribution": DISTRIBUTION,
        "version": VERSION,
        "source_commit": COMMIT,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "artifacts": [
            {
                "filename": SDIST,
                "sha256": hashlib.sha256(b"sdist").hexdigest(),
                "size": 5,
            },
            {
                "filename": WHEEL,
                "sha256": hashlib.sha256(b"wheel").hexdigest(),
                "size": 5,
            },
        ],
    }


def test_verify_reproducible_release_rejects_byte_mismatch(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second, wheel=b"different")

    with pytest.raises(ReleaseEvidenceError, match="not reproducible"):
        verify_reproducible_release(
            first,
            second,
            distribution_name=DISTRIBUTION,
            version=VERSION,
            source_commit=COMMIT,
            source_date_epoch=SOURCE_DATE_EPOCH,
        )


def test_verify_reproducible_release_rejects_missing_or_extra_artifacts(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    (second / "unexpected.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(ReleaseEvidenceError, match="exactly one wheel and one sdist"):
        verify_reproducible_release(
            first,
            second,
            distribution_name=DISTRIBUTION,
            version=VERSION,
            source_commit=COMMIT,
            source_date_epoch=SOURCE_DATE_EPOCH,
        )


def test_verify_reproducible_release_rejects_symlinked_artifact(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    second.mkdir()
    (second / SDIST).write_bytes(b"sdist")
    (second / WHEEL).symlink_to(first / WHEEL)

    with pytest.raises(ReleaseEvidenceError, match="regular non-symlink"):
        verify_reproducible_release(
            first,
            second,
            distribution_name=DISTRIBUTION,
            version=VERSION,
            source_commit=COMMIT,
            source_date_epoch=SOURCE_DATE_EPOCH,
        )


def test_verify_reproducible_release_rejects_wrong_distribution_or_version(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    wrong = second / WHEEL
    wrong.rename(second / "other_project-9.9.9-py3-none-any.whl")

    with pytest.raises(ReleaseEvidenceError, match="distribution and version"):
        verify_reproducible_release(
            first,
            second,
            distribution_name=DISTRIBUTION,
            version=VERSION,
            source_commit=COMMIT,
            source_date_epoch=SOURCE_DATE_EPOCH,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("distribution_name", "../package"),
        ("distribution_name", ""),
        ("version", "1.0/../../bad"),
        ("version", ""),
        ("source_commit", "A" * 40),
        ("source_commit", "abc"),
        ("source_date_epoch", -1),
        ("source_date_epoch", True),
    ],
)
def test_verify_reproducible_release_rejects_untrusted_metadata(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    arguments: dict[str, object] = {
        "distribution_name": DISTRIBUTION,
        "version": VERSION,
        "source_commit": COMMIT,
        "source_date_epoch": SOURCE_DATE_EPOCH,
    }
    arguments[field] = value

    with pytest.raises(ReleaseEvidenceError, match="invalid release evidence"):
        verify_reproducible_release(first, second, **arguments)  # type: ignore[arg-type]


def test_verify_reproducible_release_rejects_missing_directory(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    _write_release(existing)

    with pytest.raises(ReleaseEvidenceError, match="release directory"):
        verify_reproducible_release(
            existing,
            tmp_path / "missing",
            distribution_name=DISTRIBUTION,
            version=VERSION,
            source_commit=COMMIT,
            source_date_epoch=SOURCE_DATE_EPOCH,
        )


def test_write_release_manifest_is_atomic_and_canonical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    manifest = verify_reproducible_release(
        first,
        second,
        distribution_name=DISTRIBUTION,
        version=VERSION,
        source_commit=COMMIT,
        source_date_epoch=SOURCE_DATE_EPOCH,
    )
    output = tmp_path / "evidence" / "release-manifest.json"

    write_release_manifest(manifest, output)

    expected = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    assert output.read_text(encoding="utf-8") == expected
    assert not (output.parent / ".release-manifest.json.tmp").exists()


def test_write_release_manifest_refuses_symlink_destination(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("trusted", encoding="utf-8")
    destination = tmp_path / "manifest.json"
    destination.symlink_to(target)

    with pytest.raises(ReleaseEvidenceError, match="symlink"):
        write_release_manifest({"schema_version": 1}, destination)

    assert target.read_text(encoding="utf-8") == "trusted"
