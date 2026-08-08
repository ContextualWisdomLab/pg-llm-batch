# SPDX-License-Identifier: Apache-2.0
"""Build bounded, deterministic evidence for reproducible Python releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from itertools import islice
from pathlib import Path
from typing import Any


_DISTRIBUTION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_DISTRIBUTION_SEPARATOR_RE = re.compile(r"[-_.]+")
_HASH_CHUNK_BYTES = 1024 * 1024
_RELEASE_ARTIFACT_COUNT = 2
_RELEASE_DIRECTORY_SCAN_LIMIT = _RELEASE_ARTIFACT_COUNT + 1


class ReleaseEvidenceError(ValueError):
    """Report a fail-closed release artifact evidence violation."""


def _canonical_distribution_name(value: str) -> str:
    """Return the comparison form used for wheel and source distribution names."""
    return _DISTRIBUTION_SEPARATOR_RE.sub("-", value).lower()


def _validate_metadata(
    distribution_name: str,
    version: str,
    source_commit: str,
    source_date_epoch: int,
) -> None:
    """Reject untrusted release metadata before touching artifact paths."""
    valid = (
        isinstance(distribution_name, str)
        and _DISTRIBUTION_RE.fullmatch(distribution_name) is not None
        and isinstance(version, str)
        and _VERSION_RE.fullmatch(version) is not None
        and isinstance(source_commit, str)
        and _COMMIT_RE.fullmatch(source_commit) is not None
        and type(source_date_epoch) is int
        and source_date_epoch >= 0
    )
    if not valid:
        raise ReleaseEvidenceError("invalid release evidence metadata")


def _bounded_directory_entries(paths: Sequence[Path]) -> str:
    """Return truncated names from the already bounded directory scan."""
    return ", ".join(repr(path.name[:128]) for path in paths)


def _release_paths(directory: Path) -> tuple[Path, Path]:
    """Return one wheel and sdist after scanning at most three directory entries."""
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseEvidenceError("release directory must be a regular directory")

    paths = sorted(
        islice(directory.iterdir(), _RELEASE_DIRECTORY_SCAN_LIMIT),
        key=lambda path: path.name,
    )
    if len(paths) != _RELEASE_ARTIFACT_COUNT:
        raise ReleaseEvidenceError(
            "release directory must contain exactly one wheel and one sdist"
        )
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ReleaseEvidenceError("release artifacts must be regular non-symlink files")

    entries = _bounded_directory_entries(paths)
    wheels = [path for path in paths if path.name.endswith(".whl")]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReleaseEvidenceError(
            "release directory must contain exactly one wheel and one sdist; "
            f"entries=[{entries}]"
        )
    return wheels[0], sdists[0]


def _validate_artifact_filename(
    path: Path,
    *,
    distribution_name: str,
    version: str,
) -> None:
    """Require the artifact filename to identify the expected distribution and version."""
    if path.name.endswith(".whl"):
        parts = path.name[:-4].split("-")
        valid_shape = len(parts) >= 5
        artifact_distribution = parts[0] if valid_shape else ""
        artifact_version = parts[1] if valid_shape else ""
    else:
        expected_version_suffix = f"-{version}.tar.gz"
        valid_shape = path.name.endswith(expected_version_suffix)
        artifact_distribution = (
            path.name[: -len(expected_version_suffix)] if valid_shape else ""
        )
        artifact_version = version if valid_shape else ""

    if (
        not valid_shape
        or _canonical_distribution_name(artifact_distribution)
        != _canonical_distribution_name(distribution_name)
        or artifact_version != version
    ):
        raise ReleaseEvidenceError(
            "release artifact filename must match the expected distribution and version"
        )


def _sha256(path: Path) -> str:
    """Hash one artifact with bounded memory use."""
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_records(
    directory: Path,
    *,
    distribution_name: str,
    version: str,
) -> list[dict[str, Any]]:
    """Return source-distribution then wheel identity records."""
    wheel, sdist = _release_paths(directory)
    records: list[dict[str, Any]] = []
    for path in (sdist, wheel):
        _validate_artifact_filename(
            path,
            distribution_name=distribution_name,
            version=version,
        )
        records.append(
            {
                "filename": path.name,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )
    return records


def _ensure_manifest_parent(destination: Path) -> None:
    """Create a manifest parent without following any existing parent symlink."""
    if any(parent.is_symlink() for parent in destination.parents):
        raise ReleaseEvidenceError(
            "release manifest parent path must not contain a symlink"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)


def verify_reproducible_release(
    first_directory: str | Path,
    second_directory: str | Path,
    *,
    distribution_name: str,
    version: str,
    source_commit: str,
    source_date_epoch: int,
) -> dict[str, Any]:
    """Verify two exact-source builds and return their canonical release manifest.

    Both directories must contain exactly one regular wheel and one regular source
    distribution for the requested project version. The function bounds directory
    enumeration, streams SHA-256 calculation, compares filename/size/digest records,
    and never reads artifact contents into memory as a whole.
    """
    _validate_metadata(
        distribution_name,
        version,
        source_commit,
        source_date_epoch,
    )
    first_records = _artifact_records(
        Path(first_directory),
        distribution_name=distribution_name,
        version=version,
    )
    second_records = _artifact_records(
        Path(second_directory),
        distribution_name=distribution_name,
        version=version,
    )
    if first_records != second_records:
        raise ReleaseEvidenceError("release artifacts are not reproducible")

    return {
        "schema_version": 1,
        "distribution": distribution_name,
        "version": version,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "artifacts": first_records,
    }


def write_release_manifest(
    manifest: Mapping[str, Any],
    output_path: str | Path,
) -> None:
    """Write canonical JSON atomically without following path symlinks."""
    destination = Path(output_path)
    if destination.is_symlink():
        raise ReleaseEvidenceError("release manifest destination must not be a symlink")
    _ensure_manifest_parent(destination)
    temporary = destination.parent / f".{destination.name}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise ReleaseEvidenceError("release manifest temporary path already exists")

    payload = json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n"
    descriptor = os.open(
        temporary,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
