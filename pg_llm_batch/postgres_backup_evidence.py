# SPDX-License-Identifier: Apache-2.0
"""Inspect PostgreSQL backup artifacts through a bounded content-free evidence seam."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_DEFAULT_MAX_INSPECTION_BYTES = 64 * 1024 * 1024 * 1024
_MAX_PATH_CHARACTERS = 4096
_SECURE_FILE_FLAGS_AVAILABLE = (
    all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"))
    and os.open in getattr(os, "supports_dir_fd", frozenset())
)
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | _CLOSE_ON_EXEC
)
_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | _CLOSE_ON_EXEC
)
_ArtifactIdentity = tuple[int, int, int, int, int, int]
_BACKUP_INSPECTION_MARK = object()
_INSPECTED_BACKUP_EVIDENCE_IDS: set[int] = set()


class PostgresBackupEvidenceError(ValueError):
    """Report a fail-closed PostgreSQL backup artifact evidence violation."""


@dataclass(frozen=True, slots=True)
class PostgresBackupArtifactEvidence:
    """Represent content-free integrity evidence for one pinned backup artifact."""

    sha256: str
    size_bytes: int
    _inspection_mark: object = field(default=None, repr=False, compare=False)

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable backup artifact evidence schema."""
        return {"sha256": self.sha256, "size_bytes": self.size_bytes}


def _path_parts(path: str) -> tuple[str, tuple[str, ...], str]:
    """Return a no-parent-traversal anchor, parent components, and final filename."""
    anchor = os.sep if path.startswith(os.sep) else "."
    components: list[str] = []
    for component in path.split(os.sep):
        if component in {"", "."}:
            continue
        if component == "..":
            raise PostgresBackupEvidenceError("invalid backup artifact path")
        components.append(component)
    if not components:
        raise PostgresBackupEvidenceError("invalid backup artifact path")
    return anchor, tuple(components[:-1]), components[-1]


def _quiet_close(file_descriptor: int) -> None:
    """Attempt one descriptor close without replacing an already-selected error."""
    try:
        os.close(file_descriptor)
    except OSError:
        pass


def _close_descriptor(file_descriptor: int) -> None:
    """Close one descriptor or raise a fixed content-free cleanup error."""
    try:
        os.close(file_descriptor)
    except OSError:
        raise PostgresBackupEvidenceError(
            "PostgreSQL backup artifact descriptor could not be closed"
        ) from None


def _open_backup_artifact(path: str) -> int:
    """Open a backup by descriptor without following parent or final symlinks."""
    anchor, parent_components, artifact_name = _path_parts(path)
    try:
        parent_descriptor = os.open(anchor, _DIRECTORY_FLAGS)
    except (OSError, ValueError):
        raise PostgresBackupEvidenceError(
            "PostgreSQL backup artifact could not be opened"
        ) from None

    for component in parent_components:
        try:
            next_descriptor = os.open(
                component,
                _DIRECTORY_FLAGS,
                dir_fd=parent_descriptor,
            )
        except (OSError, ValueError):
            _quiet_close(parent_descriptor)
            raise PostgresBackupEvidenceError(
                "PostgreSQL backup artifact could not be opened"
            ) from None
        try:
            _close_descriptor(parent_descriptor)
        except PostgresBackupEvidenceError:
            _quiet_close(next_descriptor)
            raise
        parent_descriptor = next_descriptor

    try:
        artifact_descriptor = os.open(
            artifact_name,
            _FILE_FLAGS,
            dir_fd=parent_descriptor,
        )
    except (OSError, ValueError):
        _quiet_close(parent_descriptor)
        raise PostgresBackupEvidenceError(
            "PostgreSQL backup artifact could not be opened"
        ) from None

    try:
        _close_descriptor(parent_descriptor)
    except PostgresBackupEvidenceError:
        _quiet_close(artifact_descriptor)
        raise
    return artifact_descriptor


def _artifact_identity(status: os.stat_result) -> _ArtifactIdentity:
    """Return descriptor metadata that detects replacement or in-place mutation."""
    return (
        status.st_dev,
        status.st_ino,
        stat.S_IFMT(status.st_mode),
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def inspect_postgres_backup_artifact(
    path: str,
    *,
    maximum_size_bytes: int = _DEFAULT_MAX_INSPECTION_BYTES,
) -> PostgresBackupArtifactEvidence:
    """Hash one stable backup within an explicit finite byte-work budget.

    The default 64 GiB ceiling prevents an untrusted or concurrently growing file
    from turning integrity evidence into effectively unbounded hashing work. A
    deployment that intentionally handles larger backup artifacts can raise the
    keyword-only ceiling after applying its own resource and timeout policy.
    """
    if type(path) is not str or not (1 <= len(path) <= _MAX_PATH_CHARACTERS):
        raise PostgresBackupEvidenceError("invalid backup artifact path")
    if type(maximum_size_bytes) is not int or not (
        1 <= maximum_size_bytes <= _MAX_SIGNED_BIGINT
    ):
        raise PostgresBackupEvidenceError("invalid backup artifact size budget")
    if not _SECURE_FILE_FLAGS_AVAILABLE:
        raise PostgresBackupEvidenceError(
            "secure backup artifact inspection is unavailable on this platform"
        )

    file_descriptor = _open_backup_artifact(path)
    try:
        try:
            initial_status = os.fstat(file_descriptor)
        except OSError:
            raise PostgresBackupEvidenceError(
                "PostgreSQL backup artifact could not be inspected"
            ) from None

        if not stat.S_ISREG(initial_status.st_mode):
            raise PostgresBackupEvidenceError(
                "PostgreSQL backup artifact must be a regular file"
            )
        if not (0 < initial_status.st_size <= maximum_size_bytes):
            raise PostgresBackupEvidenceError(
                "PostgreSQL backup artifact must have a positive bounded size"
            )

        digest = hashlib.sha256()
        bytes_read = 0
        try:
            while bytes_read < maximum_size_bytes:
                remaining_bytes = maximum_size_bytes - bytes_read
                chunk = os.read(
                    file_descriptor,
                    min(_HASH_CHUNK_BYTES, remaining_bytes),
                )
                if not chunk:
                    break
                bytes_read += len(chunk)
                digest.update(chunk)
            final_status = os.fstat(file_descriptor)
        except OSError:
            raise PostgresBackupEvidenceError(
                "PostgreSQL backup artifact could not be read"
            ) from None

        if (
            bytes_read != initial_status.st_size
            or _artifact_identity(initial_status) != _artifact_identity(final_status)
        ):
            raise PostgresBackupEvidenceError(
                "PostgreSQL backup artifact changed during inspection"
            )

        evidence = PostgresBackupArtifactEvidence(
            sha256=digest.hexdigest(),
            size_bytes=bytes_read,
            _inspection_mark=_BACKUP_INSPECTION_MARK,
        )
        _INSPECTED_BACKUP_EVIDENCE_IDS.add(id(evidence))
    except BaseException:
        _quiet_close(file_descriptor)
        raise

    _close_descriptor(file_descriptor)
    return evidence


def postgres_backup_artifact_evidence_was_inspected(evidence: object) -> bool:
    """Return whether evidence is the exact object inspect_postgres_backup_artifact() returned."""
    return (
        type(evidence) is PostgresBackupArtifactEvidence
        and evidence._inspection_mark is _BACKUP_INSPECTION_MARK
        and id(evidence) in _INSPECTED_BACKUP_EVIDENCE_IDS
    )
