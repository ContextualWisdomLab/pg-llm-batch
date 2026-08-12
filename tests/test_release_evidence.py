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


def _verify(first: Path, second: Path, **overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "distribution_name": DISTRIBUTION,
        "version": VERSION,
        "source_commit": COMMIT,
        "source_date_epoch": SOURCE_DATE_EPOCH,
    }
    arguments.update(overrides)
    return verify_reproducible_release(  # type: ignore[arg-type,return-value]
        first,
        second,
        **arguments,
    )


def test_verify_reproducible_release_returns_bounded_deterministic_manifest(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)

    manifest = _verify(first, second)

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
        _verify(first, second)


def test_verify_reproducible_release_rejects_missing_or_extra_artifacts(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    (second / "unexpected.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(ReleaseEvidenceError, match="exactly one wheel and one sdist"):
        _verify(first, second)


def test_verify_reproducible_release_stops_after_third_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a third artifact without enumerating an unbounded directory."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    second.mkdir()
    entries = [second / SDIST, second / WHEEL, second / "unexpected.txt"]
    for entry in entries:
        entry.write_bytes(b"artifact")

    original_iterdir = Path.iterdir

    def bounded_iterdir(directory: Path):  # type: ignore[no-untyped-def]
        if directory != second:
            yield from original_iterdir(directory)
            return
        yield from entries
        raise AssertionError("release evidence scanned beyond the third entry")

    monkeypatch.setattr(Path, "iterdir", bounded_iterdir)

    with pytest.raises(ReleaseEvidenceError, match="exactly one wheel and one sdist"):
        _verify(first, second)


def test_extra_artifact_diagnostics_ignore_filesystem_iteration_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Emit one deterministic count failure for every bounded extra-file sample."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    second.mkdir()
    sdist = second / SDIST
    wheel = second / WHEEL
    first_extra = second / "first-extra.txt"
    second_extra = second / "second-extra.txt"
    for entry in (sdist, wheel, first_extra, second_extra):
        entry.write_bytes(b"artifact")

    orders = iter(
        (
            (sdist, wheel, first_extra, second_extra),
            (sdist, wheel, second_extra, first_extra),
        )
    )
    original_iterdir = Path.iterdir

    def reordered_iterdir(directory: Path):  # type: ignore[no-untyped-def]
        if directory != second:
            yield from original_iterdir(directory)
            return
        yield from next(orders)

    monkeypatch.setattr(Path, "iterdir", reordered_iterdir)
    expected = "release directory must contain exactly one wheel and one sdist"
    messages: list[str] = []

    for _ in range(2):
        with pytest.raises(ReleaseEvidenceError) as raised:
            _verify(first, second)
        messages.append(str(raised.value))

    assert messages == [expected, expected]


def test_verify_reproducible_release_rejects_symlinked_artifact(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    second.mkdir()
    (second / SDIST).write_bytes(b"sdist")
    (second / WHEEL).symlink_to(first / WHEEL)

    with pytest.raises(ReleaseEvidenceError, match="regular non-symlink"):
        _verify(first, second)


def test_verify_reproducible_release_rejects_directory_artifact(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    second.mkdir()
    (second / SDIST).write_bytes(b"sdist")
    (second / WHEEL).mkdir()

    with pytest.raises(ReleaseEvidenceError, match="regular non-symlink"):
        _verify(first, second)


def test_verify_reproducible_release_rejects_wrong_artifact_kinds(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    second.mkdir()
    (second / SDIST).write_bytes(b"sdist")
    (second / "unexpected.txt").write_bytes(b"other")

    with pytest.raises(ReleaseEvidenceError, match="exactly one wheel and one sdist"):
        _verify(first, second)


@pytest.mark.parametrize(
    "wrong_name",
    [
        "other_project-0.1.0-py3-none-any.whl",
        "pg_llm_batch-9.9.9-py3-none-any.whl",
        "malformed.whl",
    ],
)
def test_verify_reproducible_release_rejects_wrong_wheel_identity(
    tmp_path: Path,
    wrong_name: str,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    (second / WHEEL).rename(second / wrong_name)

    with pytest.raises(ReleaseEvidenceError, match="distribution and version"):
        _verify(first, second)


def test_verify_reproducible_release_rejects_wrong_sdist_identity(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    (second / SDIST).rename(second / "pg_llm_batch-9.9.9.tar.gz")

    with pytest.raises(ReleaseEvidenceError, match="distribution and version"):
        _verify(first, second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("distribution_name", "../package"),
        ("distribution_name", ""),
        ("distribution_name", None),
        ("version", "1.0/../../bad"),
        ("version", ""),
        ("version", 1),
        ("source_commit", "A" * 40),
        ("source_commit", "abc"),
        ("source_commit", None),
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

    with pytest.raises(ReleaseEvidenceError, match="invalid release evidence"):
        _verify(first, second, **{field: value})


def test_verify_reproducible_release_rejects_missing_directory(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    _write_release(existing)

    with pytest.raises(ReleaseEvidenceError, match="release directory"):
        _verify(existing, tmp_path / "missing")


def test_verify_reproducible_release_rejects_symlinked_directory(tmp_path: Path) -> None:
    first = tmp_path / "first"
    target = tmp_path / "target"
    linked = tmp_path / "linked"
    _write_release(first)
    _write_release(target)
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(ReleaseEvidenceError, match="release directory"):
        _verify(first, linked)


def test_write_release_manifest_is_atomic_and_canonical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    manifest = _verify(first, second)
    output = tmp_path / "evidence" / "release-manifest.json"
    output.parent.mkdir()
    output.write_text("predecessor", encoding="utf-8")

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


@pytest.mark.parametrize("nested_parent", [False, True])
def test_write_release_manifest_refuses_symlinked_parent_component(
    tmp_path: Path,
    nested_parent: bool,
) -> None:
    """Never write manifest bytes through a direct or nested parent symlink."""
    target = tmp_path / "outside"
    target.mkdir()
    linked_parent = tmp_path / "evidence"
    linked_parent.symlink_to(target, target_is_directory=True)
    parent = linked_parent / "nested" if nested_parent else linked_parent
    destination = parent / "release-manifest.json"

    with pytest.raises(ReleaseEvidenceError, match="parent.*symlink"):
        write_release_manifest({"schema_version": 1}, destination)

    escaped_destination = (
        target / "nested" / "release-manifest.json"
        if nested_parent
        else target / "release-manifest.json"
    )
    assert not escaped_destination.exists()


def test_write_release_manifest_refuses_existing_temporary_file(tmp_path: Path) -> None:
    destination = tmp_path / "manifest.json"
    temporary = tmp_path / ".manifest.json.tmp"
    temporary.write_text("untrusted", encoding="utf-8")

    with pytest.raises(ReleaseEvidenceError, match="temporary path"):
        write_release_manifest({"schema_version": 1}, destination)

    assert temporary.read_text(encoding="utf-8") == "untrusted"


def test_write_release_manifest_refuses_dangling_temporary_symlink(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "manifest.json"
    temporary = tmp_path / ".manifest.json.tmp"
    temporary.symlink_to(tmp_path / "missing-target")

    with pytest.raises(ReleaseEvidenceError, match="temporary path"):
        write_release_manifest({"schema_version": 1}, destination)
