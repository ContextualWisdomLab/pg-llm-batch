# SPDX-License-Identifier: Apache-2.0
"""Inspect PostgreSQL backup artifacts through a bounded content-free evidence seam."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_MAX_PATH_CHARACTERS = 4096
_SECURE_FILE_FLAGS_AVAILABLE = all(
    hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_NONBLOCK")
)
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | _CLOSE_ON_EXEC
)
_ArtifactIdentity = tuple[int, int, int, int, int, int]


class PostgresBackupEvidenceError(ValueError):
    """Report a fail-closed PostgreSQL backup artifact evidence violation."""


@dataclass(frozen=True, slots=True)
class PostgresBackupArtifactEvidence:
    """Represent content-free integrity evidence for one pinned backup artifact."""

    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable backup artifact evidence schema."""
        return {"sha256": self.sha256, "size_bytes": self.size_bytes}


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


def inspect_postgres_backup_artifact(path: str) -> PostgresBackupArtifactEvidence:
    """Hash one stable regular backup file without returning its path or content."""
    if type(path) is not str or not (1 <= len(path) <= _MAX_PATH_CHARACTERS):
        raise PostgresBackupEvidenceError("invalid backup artifact path")
    if not _SECURE_FILE_FLAGS_AVAILABLE:
        raise PostgresBackupEvidenceError(
            "secure backup artifact inspection is unavailable on this platform"
        )

    try:
        file_descriptor = os.open(path, _FILE_FLAGS)
    except (OSError, ValueError):
        raise PostgresBackupEvidenceError(
            "PostgreSQL backup artifact could not be opened"
        ) from None

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
        if not (0 < initial_status.st_size <= _MAX_SIGNED_BIGINT):
            raise PostgresBackupEvidenceError(
                "PostgreSQL backup artifact must have a positive bounded size"
            )

        digest = hashlib.sha256()
        bytes_read = 0
        try:
            while chunk := os.read(file_descriptor, _HASH_CHUNK_BYTES):
                digest.update(chunk)
                bytes_read += len(chunk)
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

        return PostgresBackupArtifactEvidence(
            sha256=digest.hexdigest(),
            size_bytes=bytes_read,
        )
    finally:
        os.close(file_descriptor)
