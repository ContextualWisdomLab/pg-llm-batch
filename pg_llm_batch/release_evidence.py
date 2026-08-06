# SPDX-License-Identifier: Apache-2.0
"""Build bounded, deterministic evidence for reproducible Python releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
_SECURE_ARTIFACT_DIR_FD_FUNCTIONS = frozenset((os.open,))
_SECURE_ARTIFACT_FD_FUNCTIONS = frozenset((os.scandir,))
_SECURE_ARTIFACT_FLAGS_AVAILABLE = all(
    hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
)
_SECURE_MANIFEST_DIR_FD_FUNCTIONS = frozenset(
    (os.open, os.mkdir, os.stat, os.unlink, os.rename)
)
_SECURE_MANIFEST_FOLLOW_FUNCTIONS = frozenset((os.stat,))
_SECURE_MANIFEST_FLAGS_AVAILABLE = hasattr(os, "O_DIRECTORY") and hasattr(
    os, "O_NOFOLLOW"
)
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_ARTIFACT_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | _CLOSE_ON_EXEC
)
_ARTIFACT_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | _CLOSE_ON_EXEC
)
_MANIFEST_DIRECTORY_FLAGS = _ARTIFACT_DIRECTORY_FLAGS
_MANIFEST_TEMPORARY_FLAGS = (
    os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | _CLOSE_ON_EXEC
)


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


def _bounded_directory_entries(names: Sequence[str]) -> str:
    """Return truncated names from an already bounded directory scan."""
    return ", ".join(repr(name[:128]) for name in names)


def _secure_artifact_reads_supported() -> bool:
    """Return whether the runtime exposes required descriptor-bound read primitives."""
    return (
        _SECURE_ARTIFACT_FLAGS_AVAILABLE
        and _SECURE_ARTIFACT_DIR_FD_FUNCTIONS.issubset(os.supports_dir_fd)
        and _SECURE_ARTIFACT_FD_FUNCTIONS.issubset(os.supports_fd)
    )


def _directory_path_parts(directory: Path) -> tuple[str, tuple[str, ...]]:
    """Return an anchor and normalized components for no-follow directory traversal."""
    parts = directory.parts
    if directory.is_absolute():
        anchor = directory.anchor
        parts = parts[1:]
    else:
        anchor = "."
    if ".." in parts:
        raise ReleaseEvidenceError("release directory parent traversal is not allowed")
    return anchor, parts


def _open_release_directory(directory: Path) -> int:
    """Open a release directory through held descriptors without following symlinks."""
    anchor, parts = _directory_path_parts(directory)
    try:
        directory_descriptor = os.open(anchor, _ARTIFACT_DIRECTORY_FLAGS)
    except (OSError, ValueError):
        raise ReleaseEvidenceError("release directory root could not be opened") from None

    try:
        for component in parts:
            try:
                next_descriptor = os.open(
                    component,
                    _ARTIFACT_DIRECTORY_FLAGS,
                    dir_fd=directory_descriptor,
                )
            except (OSError, ValueError):
                raise ReleaseEvidenceError(
                    "release directory path must not contain a symlink "
                    "and must contain only directories"
                ) from None
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        return directory_descriptor
    except BaseException:
        os.close(directory_descriptor)
        raise


def _scan_release_names(directory_descriptor: int) -> tuple[str, ...]:
    """Return at most three sorted names from one descriptor-pinned directory."""
    try:
        with os.scandir(directory_descriptor) as entries:
            return tuple(
                sorted(
                    (entry.name for entry in islice(entries, _RELEASE_DIRECTORY_SCAN_LIMIT))
                )
            )
    except (OSError, ValueError):
        raise ReleaseEvidenceError("release directory could not be inspected") from None


def _release_names(names: Sequence[str]) -> tuple[str, str]:
    """Return one wheel and source-distribution name from a bounded name sample."""
    if len(names) != _RELEASE_ARTIFACT_COUNT:
        raise ReleaseEvidenceError(
            "release directory must contain exactly one wheel and one sdist"
        )

    entries = _bounded_directory_entries(names)
    wheels = [name for name in names if name.endswith(".whl")]
    sdists = [name for name in names if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReleaseEvidenceError(
            "release directory must contain exactly one wheel and one sdist; "
            f"entries=[{entries}]"
        )
    return wheels[0], sdists[0]


def _validate_artifact_filename(
    name: str,
    *,
    distribution_name: str,
    version: str,
) -> None:
    """Require an artifact filename to identify the expected project and version."""
    if name.endswith(".whl"):
        parts = name[:-4].split("-")
        valid_shape = len(parts) >= 5
        artifact_distribution = parts[0] if valid_shape else ""
        artifact_version = parts[1] if valid_shape else ""
    else:
        expected_version_suffix = f"-{version}.tar.gz"
        valid_shape = name.endswith(expected_version_suffix)
        artifact_distribution = name[: -len(expected_version_suffix)] if valid_shape else ""
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


def _artifact_identity(status: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return inode metadata that must remain stable while artifact bytes are read."""
    return (
        status.st_dev,
        status.st_ino,
        stat.S_IFMT(status.st_mode),
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _artifact_record(directory_descriptor: int, name: str) -> dict[str, Any]:
    """Read one regular non-symlink artifact through its pinned directory descriptor."""
    try:
        artifact_descriptor = os.open(
            name,
            _ARTIFACT_FILE_FLAGS,
            dir_fd=directory_descriptor,
        )
    except (OSError, ValueError):
        raise ReleaseEvidenceError(
            "release artifacts must be regular non-symlink files"
        ) from None

    try:
        try:
            initial_status = os.fstat(artifact_descriptor)
        except OSError:
            raise ReleaseEvidenceError("release artifact could not be inspected") from None
        if not stat.S_ISREG(initial_status.st_mode):
            raise ReleaseEvidenceError(
                "release artifacts must be regular non-symlink files"
            )

        digest = hashlib.sha256()
        bytes_read = 0
        try:
            while chunk := os.read(artifact_descriptor, _HASH_CHUNK_BYTES):
                digest.update(chunk)
                bytes_read += len(chunk)
            final_status = os.fstat(artifact_descriptor)
        except OSError:
            raise ReleaseEvidenceError("release artifact could not be read") from None

        if (
            bytes_read != initial_status.st_size
            or _artifact_identity(initial_status) != _artifact_identity(final_status)
        ):
            raise ReleaseEvidenceError("release artifact changed during verification")
        return {
            "filename": name,
            "sha256": digest.hexdigest(),
            "size": bytes_read,
        }
    finally:
        os.close(artifact_descriptor)


def _artifact_records(
    directory: Path,
    *,
    distribution_name: str,
    version: str,
) -> list[dict[str, Any]]:
    """Return source-distribution then wheel records from one pinned directory."""
    directory_descriptor = _open_release_directory(directory)
    try:
        initial_names = _scan_release_names(directory_descriptor)
        wheel, sdist = _release_names(initial_names)
        records: list[dict[str, Any]] = []
        for name in (sdist, wheel):
            _validate_artifact_filename(
                name,
                distribution_name=distribution_name,
                version=version,
            )
            records.append(_artifact_record(directory_descriptor, name))
        if _scan_release_names(directory_descriptor) != initial_names:
            raise ReleaseEvidenceError("release directory changed during verification")
        return records
    finally:
        os.close(directory_descriptor)


def _secure_manifest_writes_supported() -> bool:
    """Return whether the runtime exposes every required no-follow primitive."""
    return (
        _SECURE_MANIFEST_FLAGS_AVAILABLE
        and _SECURE_MANIFEST_DIR_FD_FUNCTIONS.issubset(os.supports_dir_fd)
        and _SECURE_MANIFEST_FOLLOW_FUNCTIONS.issubset(os.supports_follow_symlinks)
    )


def _manifest_path_parts(destination: Path) -> tuple[str, tuple[str, ...], str]:
    """Return an anchor, parent components, and final name for secure traversal."""
    destination_name = destination.name
    if destination_name in {"", ".", ".."}:
        raise ReleaseEvidenceError("release manifest destination name is invalid")

    parent_parts = destination.parent.parts
    if destination.is_absolute():
        anchor = destination.anchor
        parent_parts = parent_parts[1:]
    else:
        anchor = "."
    if ".." in parent_parts:
        raise ReleaseEvidenceError("release manifest parent traversal is not allowed")
    return anchor, parent_parts, destination_name


def _open_manifest_parent(destination: Path) -> tuple[int, str]:
    """Open or create the final parent by descriptor without following symlinks."""
    anchor, parent_parts, destination_name = _manifest_path_parts(destination)
    try:
        parent_descriptor = os.open(anchor, _MANIFEST_DIRECTORY_FLAGS)
    except (OSError, ValueError):
        raise ReleaseEvidenceError("release manifest parent root could not be opened") from None

    try:
        for component in parent_parts:
            try:
                os.mkdir(component, 0o700, dir_fd=parent_descriptor)
            except FileExistsError:
                pass
            except (OSError, ValueError):
                raise ReleaseEvidenceError(
                    "release manifest parent directory could not be created"
                ) from None

            try:
                next_descriptor = os.open(
                    component,
                    _MANIFEST_DIRECTORY_FLAGS,
                    dir_fd=parent_descriptor,
                )
            except (OSError, ValueError):
                raise ReleaseEvidenceError(
                    "release manifest parent path must not contain a symlink "
                    "and must contain only directories"
                ) from None
            os.close(parent_descriptor)
            parent_descriptor = next_descriptor
        return parent_descriptor, destination_name
    except BaseException:
        os.close(parent_descriptor)
        raise


def _validate_manifest_destination(parent_descriptor: int, destination_name: str) -> None:
    """Require the descriptor-relative destination to be absent or a regular file."""
    try:
        destination_status = os.stat(
            destination_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        raise ReleaseEvidenceError(
            "release manifest destination could not be inspected"
        ) from None

    if stat.S_ISLNK(destination_status.st_mode):
        raise ReleaseEvidenceError("release manifest destination must not be a symlink")
    if not stat.S_ISREG(destination_status.st_mode):
        raise ReleaseEvidenceError(
            "release manifest destination must be absent or a regular file"
        )


def _remove_owned_temporary(parent_descriptor: int, temporary_name: str) -> None:
    """Remove only the temporary entry created by the current invocation."""
    try:
        os.unlink(temporary_name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        raise ReleaseEvidenceError(
            "release manifest temporary cleanup failed"
        ) from None


def _write_manifest_payload(
    payload: str,
    *,
    parent_descriptor: int,
    destination_name: str,
) -> None:
    """Write, synchronize, and atomically replace a descriptor-relative manifest."""
    temporary_name = f".{destination_name}.tmp"
    temporary_descriptor: int | None = None
    temporary_created = False
    try:
        try:
            temporary_descriptor = os.open(
                temporary_name,
                _MANIFEST_TEMPORARY_FLAGS,
                0o600,
                dir_fd=parent_descriptor,
            )
        except FileExistsError:
            raise ReleaseEvidenceError(
                "release manifest temporary path already exists"
            ) from None
        except (OSError, ValueError):
            raise ReleaseEvidenceError(
                "release manifest temporary file could not be created"
            ) from None
        temporary_created = True

        try:
            handle = os.fdopen(
                temporary_descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            )
        except (OSError, ValueError):
            raise ReleaseEvidenceError("release manifest write failed") from None
        temporary_descriptor = None
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            raise ReleaseEvidenceError("release manifest write failed") from None

        try:
            os.rename(
                temporary_name,
                destination_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        except (OSError, ValueError):
            raise ReleaseEvidenceError(
                "release manifest atomic replacement failed"
            ) from None
        temporary_created = False

        try:
            os.fsync(parent_descriptor)
        except OSError:
            raise ReleaseEvidenceError(
                "release manifest directory synchronization failed"
            ) from None
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if temporary_created:
            _remove_owned_temporary(parent_descriptor, temporary_name)


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
    distribution for the requested project version. The function pins directory
    traversal and artifact reads to descriptors, bounds enumeration, streams SHA-256,
    rejects concurrent identity changes, and never loads whole artifacts into memory.
    """
    _validate_metadata(
        distribution_name,
        version,
        source_commit,
        source_date_epoch,
    )
    if not _secure_artifact_reads_supported():
        raise ReleaseEvidenceError(
            "secure release artifact verification requires descriptor-relative "
            "no-follow support"
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
    """Write canonical JSON atomically through a pinned parent descriptor.

    The writer fails closed unless descriptor-relative operations and no-follow
    flags are available. Every parent component, the temporary file, and the
    atomic replacement are resolved relative to held directory descriptors.
    """
    payload = json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n"
    if not _secure_manifest_writes_supported():
        raise ReleaseEvidenceError(
            "secure release manifest writes require descriptor-relative "
            "no-follow support"
        )

    parent_descriptor, destination_name = _open_manifest_parent(Path(output_path))
    try:
        _validate_manifest_destination(parent_descriptor, destination_name)
        _write_manifest_payload(
            payload,
            parent_descriptor=parent_descriptor,
            destination_name=destination_name,
        )
    finally:
        os.close(parent_descriptor)
