# SPDX-License-Identifier: Apache-2.0
"""Bind one bounded PostgreSQL archive-recovery restore command."""

from __future__ import annotations

import re
from dataclasses import dataclass


_MAX_HELPER_EXECUTABLE_BYTES = 512
_HELPER_EXECUTABLE_RE = re.compile(
    r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z"
)
_INVALID_PATH_SEGMENTS = frozenset({".", ".."})


class PostgresRestoreCommandError(ValueError):
    """Report a fail-closed PostgreSQL restore-helper authority violation."""


def _validate_helper_executable(helper_executable: object) -> str:
    """Return one bounded shell-inert absolute helper executable token."""
    if type(helper_executable) is not str:
        raise PostgresRestoreCommandError(
            "invalid PostgreSQL restore helper executable"
        )
    try:
        encoded_size = len(helper_executable.encode("ascii"))
    except UnicodeError:
        raise PostgresRestoreCommandError(
            "invalid PostgreSQL restore helper executable"
        ) from None
    if not 1 <= encoded_size <= _MAX_HELPER_EXECUTABLE_BYTES:
        raise PostgresRestoreCommandError(
            "invalid PostgreSQL restore helper executable"
        )
    if _HELPER_EXECUTABLE_RE.fullmatch(helper_executable) is None:
        raise PostgresRestoreCommandError(
            "invalid PostgreSQL restore helper executable"
        )
    if any(
        segment in _INVALID_PATH_SEGMENTS
        for segment in helper_executable.split("/")[1:]
    ):
        raise PostgresRestoreCommandError(
            "invalid PostgreSQL restore helper executable"
        )
    return helper_executable


@dataclass(frozen=True, slots=True)
class PostgresArchiveRestoreCommand:
    """Represent one deterministic PostgreSQL archive-recovery command setting.

    ``helper_executable`` is the only caller-provided authority and is constrained to
    one bounded canonical absolute POSIX token. PostgreSQL supplies ``%f`` (requested
    archive filename) and ``%p`` (destination path) when it executes
    ``restore_command``. The object accepts no caller-provided shell text, arguments,
    archive path, credential, or alternate placeholder ordering.

    This value does not inspect or attest the helper executable, retrieve WAL, prove
    archive continuity, start PostgreSQL, execute replay, promote a target, or prove
    RPO/RTO. Those authorities require separate deployment and recovery evidence.
    """

    helper_executable: str

    def __post_init__(self) -> None:
        """Reject direct construction that bypasses helper-token validation."""
        _validate_helper_executable(self.helper_executable)

    def server_setting(self) -> tuple[str, str]:
        """Return PostgreSQL's restore-command setting with fixed server placeholders."""
        return (
            "restore_command",
            f"{self.helper_executable} %f %p",
        )


def bind_postgres_archive_restore_command(
    helper_executable: str,
) -> PostgresArchiveRestoreCommand:
    """Bind a reviewed restore helper without accepting free-form shell authority.

    PostgreSQL archive recovery requires ``restore_command`` and expands ``%f`` to the
    requested WAL filename and ``%p`` to its destination path before invoking the
    configured command through the local shell. This binder therefore accepts only one
    shell-inert absolute helper executable token and fixes both placeholders and their
    order. The helper must independently return nonzero when an archive member is
    unavailable and must own all archive access, integrity, credential, and copy
    semantics.

    The package does not inspect helper ownership/content here, configure an archive,
    write PostgreSQL configuration, create ``recovery.signal``, start recovery, replay
    WAL, or authorize promotion. A later operator-controlled composition must prove
    those boundaries separately.
    """
    validated_helper = _validate_helper_executable(helper_executable)
    return PostgresArchiveRestoreCommand(helper_executable=validated_helper)
