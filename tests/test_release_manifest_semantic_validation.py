# SPDX-License-Identifier: Apache-2.0
"""Fail-closed contracts for persisted canonical release manifests."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from pg_llm_batch.release_evidence import ReleaseEvidenceError, write_release_manifest


DISTRIBUTION = "pg-llm-batch"
VERSION = "0.1.0"
COMMIT = "a" * 40
SOURCE_DATE_EPOCH = 1_786_000_000
SDIST = "pg_llm_batch-0.1.0.tar.gz"
WHEEL = "pg_llm_batch-0.1.0-py3-none-any.whl"
SDIST_SHA256 = "b" * 64
WHEEL_SHA256 = "c" * 64
# RFC 8259 §6 defines this as the integer range with exact interoperable value agreement.
MAX_INTEROPERABLE_JSON_INTEGER = (1 << 53) - 1


def _canonical_manifest() -> dict[str, Any]:
    """Return the exact manifest shape produced by verified release evidence."""
    return {
        "schema_version": 1,
        "distribution": DISTRIBUTION,
        "version": VERSION,
        "source_commit": COMMIT,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "artifacts": [
            {"filename": SDIST, "sha256": SDIST_SHA256, "size": 5},
            {"filename": WHEEL, "sha256": WHEEL_SHA256, "size": 5},
        ],
    }


def _assert_rejected_without_filesystem_mutation(
    manifest: Mapping[str, Any],
    output: Path,
) -> None:
    """Require semantic rejection before parent creation or manifest replacement."""
    with pytest.raises(ReleaseEvidenceError, match="invalid release manifest"):
        write_release_manifest(manifest, output)
    assert not output.parent.exists()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda manifest: manifest.pop("version"),
        lambda manifest: manifest.update({"unexpected": "field"}),
        lambda manifest: manifest.update({"schema_version": 2}),
        lambda manifest: manifest.update({"schema_version": True}),
        lambda manifest: manifest.update({"schema_version": 1.0}),
        lambda manifest: manifest.update({"distribution": "../package"}),
        lambda manifest: manifest.update({"version": "1.0/../../bad"}),
        lambda manifest: manifest.update({"source_commit": "A" * 40}),
        lambda manifest: manifest.update({"source_commit": "g" * 40}),
        lambda manifest: manifest.update({"source_date_epoch": True}),
        lambda manifest: manifest.update({"source_date_epoch": -1}),
        lambda manifest: manifest.update(
            {"source_date_epoch": float(SOURCE_DATE_EPOCH)}
        ),
        lambda manifest: manifest.update(
            {"source_date_epoch": MAX_INTEROPERABLE_JSON_INTEGER + 1}
        ),
        lambda manifest: manifest.update({"artifacts": []}),
        lambda manifest: manifest["artifacts"].append(
            dict(manifest["artifacts"][0])
        ),
    ],
)
def test_write_release_manifest_rejects_noncanonical_top_level_data_before_io(
    tmp_path: Path,
    mutator: Any,
) -> None:
    """Reject malformed canonical evidence before creating its destination parent."""
    manifest = _canonical_manifest()
    mutator(manifest)

    _assert_rejected_without_filesystem_mutation(
        manifest,
        tmp_path / "evidence" / "release-manifest.json",
    )


@pytest.mark.parametrize("artifact_index", [0, 1])
@pytest.mark.parametrize(
    "artifact_mutator",
    [
        lambda artifact: artifact.pop("size"),
        lambda artifact: artifact.update({"unexpected": "field"}),
        lambda artifact: artifact.update({"filename": "other-0.1.0.tar.gz"}),
        lambda artifact: artifact.update({"sha256": "B" * 64}),
        lambda artifact: artifact.update({"sha256": "g" * 64}),
        lambda artifact: artifact.update({"sha256": "b" * 63}),
        lambda artifact: artifact.update({"size": True}),
        lambda artifact: artifact.update({"size": 5.0}),
        lambda artifact: artifact.update({"size": -1}),
        lambda artifact: artifact.update(
            {"size": MAX_INTEROPERABLE_JSON_INTEGER + 1}
        ),
    ],
)
def test_write_release_manifest_rejects_noncanonical_artifact_records_before_io(
    tmp_path: Path,
    artifact_index: int,
    artifact_mutator: Any,
) -> None:
    """Reject malformed sdist and wheel identity, digest, and size claims before I/O."""
    manifest = _canonical_manifest()
    artifact_mutator(manifest["artifacts"][artifact_index])

    _assert_rejected_without_filesystem_mutation(
        manifest,
        tmp_path / "evidence" / "release-manifest.json",
    )


def test_write_release_manifest_rejects_duplicate_or_reordered_artifact_identity_before_io(
    tmp_path: Path,
) -> None:
    """Require exactly one canonical sdist followed by exactly one canonical wheel."""
    output = tmp_path / "evidence" / "release-manifest.json"

    duplicate = _canonical_manifest()
    duplicate["artifacts"][1] = dict(duplicate["artifacts"][0])
    _assert_rejected_without_filesystem_mutation(duplicate, output)

    reordered = _canonical_manifest()
    reordered["artifacts"].reverse()
    _assert_rejected_without_filesystem_mutation(reordered, output)


class _ExplosiveMapping(Mapping[str, Any]):
    """Expose whether arbitrary caller mapping behavior runs before validation."""

    def __getitem__(self, key: str) -> Any:
        raise AssertionError(f"caller mapping materialized key {key!r}")

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("caller mapping iteration executed")

    def __len__(self) -> int:
        raise AssertionError("caller mapping length executed")


def test_write_release_manifest_rejects_arbitrary_mapping_without_invoking_it(
    tmp_path: Path,
) -> None:
    """Reject behavior-bearing mappings before dict materialization or filesystem I/O."""
    output = tmp_path / "evidence" / "release-manifest.json"

    with pytest.raises(ReleaseEvidenceError, match="invalid release manifest"):
        write_release_manifest(_ExplosiveMapping(), output)

    assert not output.parent.exists()


class _DictSubclass(dict[str, Any]):
    """Represent caller behavior hidden behind a dict-compatible subclass."""


class _ListSubclass(list[dict[str, Any]]):
    """Represent caller behavior hidden behind a list-compatible subclass."""


class _StringSubclass(str):
    """Represent caller behavior hidden behind a str-compatible subclass."""


class _IntSubclass(int):
    """Represent caller behavior hidden behind an int-compatible subclass."""


def test_write_release_manifest_requires_exact_builtin_container_types(tmp_path: Path) -> None:
    """Accept only built-in dict/list containers at the persistence trust boundary."""
    output = tmp_path / "evidence" / "release-manifest.json"

    top_level = _DictSubclass(_canonical_manifest())
    _assert_rejected_without_filesystem_mutation(top_level, output)

    artifact_list = _canonical_manifest()
    artifact_list["artifacts"] = _ListSubclass(artifact_list["artifacts"])
    _assert_rejected_without_filesystem_mutation(artifact_list, output)

    artifact_tuple = _canonical_manifest()
    artifact_tuple["artifacts"] = tuple(artifact_tuple["artifacts"])
    _assert_rejected_without_filesystem_mutation(artifact_tuple, output)

    for artifact_index in range(2):
        artifact_record = _canonical_manifest()
        artifact_record["artifacts"][artifact_index] = _DictSubclass(
            artifact_record["artifacts"][artifact_index]
        )
        _assert_rejected_without_filesystem_mutation(artifact_record, output)

        artifact_mapping = _canonical_manifest()
        artifact_mapping["artifacts"][artifact_index] = _ExplosiveMapping()
        _assert_rejected_without_filesystem_mutation(artifact_mapping, output)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", _IntSubclass(1)),
        ("distribution", _StringSubclass(DISTRIBUTION)),
        ("version", _StringSubclass(VERSION)),
        ("source_commit", _StringSubclass(COMMIT)),
        ("source_date_epoch", _IntSubclass(SOURCE_DATE_EPOCH)),
    ],
)
def test_write_release_manifest_requires_exact_builtin_top_level_primitive_types(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    """Reject primitive subclasses even when values equal canonical metadata."""
    manifest = _canonical_manifest()
    manifest[field] = value

    _assert_rejected_without_filesystem_mutation(
        manifest,
        tmp_path / "evidence" / "release-manifest.json",
    )


@pytest.mark.parametrize(
    ("artifact_index", "field", "value"),
    [
        (0, "filename", _StringSubclass(SDIST)),
        (0, "sha256", _StringSubclass(SDIST_SHA256)),
        (0, "size", _IntSubclass(5)),
        (1, "filename", _StringSubclass(WHEEL)),
        (1, "sha256", _StringSubclass(WHEEL_SHA256)),
        (1, "size", _IntSubclass(5)),
    ],
)
def test_write_release_manifest_requires_exact_builtin_artifact_primitive_types(
    tmp_path: Path,
    artifact_index: int,
    field: str,
    value: Any,
) -> None:
    """Reject primitive subclasses in both artifact records before persistence."""
    manifest = _canonical_manifest()
    manifest["artifacts"][artifact_index][field] = value

    _assert_rejected_without_filesystem_mutation(
        manifest,
        tmp_path / "evidence" / "release-manifest.json",
    )


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "distribution",
        "version",
        "source_commit",
        "source_date_epoch",
        "artifacts",
    ],
)
def test_write_release_manifest_requires_exact_builtin_top_level_key_types(
    tmp_path: Path,
    field: str,
) -> None:
    """Reject every str-subclass top-level key before persistence."""
    manifest = _canonical_manifest()
    value = manifest.pop(field)
    manifest[_StringSubclass(field)] = value

    _assert_rejected_without_filesystem_mutation(
        manifest,
        tmp_path / "evidence" / "release-manifest.json",
    )


@pytest.mark.parametrize("artifact_index", [0, 1])
@pytest.mark.parametrize("field", ["filename", "sha256", "size"])
def test_write_release_manifest_requires_exact_builtin_artifact_key_types(
    tmp_path: Path,
    artifact_index: int,
    field: str,
) -> None:
    """Reject every str-subclass key in both artifact records before persistence."""
    manifest = _canonical_manifest()
    value = manifest["artifacts"][artifact_index].pop(field)
    manifest["artifacts"][artifact_index][_StringSubclass(field)] = value

    _assert_rejected_without_filesystem_mutation(
        manifest,
        tmp_path / "evidence" / "release-manifest.json",
    )
