"""Bounded caller-selected ``pg_service.conf`` resolver for the pg8000 candidate.

PostgreSQL service files are an INI-like indirection from a service name to
connection parameters. pg8000 does not implement libpq's service-file lookup,
and the database driver must not silently acquire process-environment or
filesystem-discovery authority while pg-llm-batch evaluates a replacement for
Psycopg. This candidate resolver therefore reads exactly one caller-selected
file, applies a finite byte budget, and returns only the exact target stanza.
Relative caller paths are bound to the working directory that existed when the
resolver was constructed. The selected parent-directory and final regular-file
identities are retained as well, and each read is anchored to a descriptor for
that exact directory, so later working-directory, parent-path, or regular-file
replacement cannot redirect database connection authority.

The parser intentionally does not implement libpq LDAP lookup or ambient
``PGSERVICEFILE``/user/system search precedence. Those capabilities require
separate security and compatibility evidence. The returned mapping is validated
again by :class:`Pg8000CandidateDriverAdapter`, so unsupported PostgreSQL
connection parameters remain fail closed at the driver boundary.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .pg8000_candidate_driver_port import Pg8000CandidateInvalidConninfoError


_MAX_SERVICE_FILE_BYTES = 64 * 1024


def _invalid_service_file(*, unsupported: bool = False) -> Pg8000CandidateInvalidConninfoError:
    """Return one non-content-bearing error for service-file resolution failures."""
    if unsupported:
        return Pg8000CandidateInvalidConninfoError(
            "PostgreSQL connection selector is unsupported"
        )
    return Pg8000CandidateInvalidConninfoError(
        "PostgreSQL connection selector is invalid"
    )


def _has_disallowed_control(value: str) -> bool:
    """Reject framing controls while allowing ordinary horizontal whitespace."""
    return any(
        (ord(character) < 0x20 and character != "\t") or ord(character) == 0x7F
        for character in value
    )


def _validate_service_name(service_name: object) -> str:
    """Validate one exact service identity without normalizing caller authority."""
    if (
        type(service_name) is not str
        or not service_name
        or service_name != service_name.strip()
        or _has_disallowed_control(service_name)
        or "[" in service_name
        or "]" in service_name
    ):
        raise _invalid_service_file()
    return service_name


def _service_file_snapshot(observed: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Capture metadata that must remain stable while service bytes are retained."""
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _close_descriptor(descriptor: int, *, preserve_primary_error: bool) -> None:
    """Close one retained descriptor without replacing an established primary error."""
    try:
        os.close(descriptor)
    except OSError:
        if preserve_primary_error:
            return
        raise _invalid_service_file() from None


def _capture_parent_identity(parent: Path) -> tuple[int, int]:
    """Bind the construction-time directory that owns the selected file name."""
    try:
        observed = os.stat(parent)
    except (OSError, ValueError):
        raise _invalid_service_file() from None
    if not stat.S_ISDIR(observed.st_mode):
        raise _invalid_service_file()
    return observed.st_dev, observed.st_ino


def _open_selected_parent(parent: Path, expected_identity: tuple[int, int]) -> int:
    """Open and authenticate the selected parent before directory-relative file I/O."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        descriptor = os.open(parent, flags)
    except (OSError, ValueError):
        raise _invalid_service_file() from None

    primary_error: BaseException | None = None
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or (observed.st_dev, observed.st_ino) != expected_identity
        ):
            raise _invalid_service_file()
    except Pg8000CandidateInvalidConninfoError as exc:
        primary_error = exc
        raise
    except (OSError, ValueError) as exc:
        primary_error = exc
        raise _invalid_service_file() from None
    finally:
        if primary_error is not None:
            _close_descriptor(descriptor, preserve_primary_error=True)

    return descriptor


def _selected_regular_file_identity(
    file_name: str,
    parent_descriptor: int,
) -> tuple[int, int]:
    """Return one regular non-symlink final-component identity or fail closed."""
    try:
        selected = os.lstat(file_name, dir_fd=parent_descriptor)
    except (OSError, ValueError, NotImplementedError):
        raise _invalid_service_file() from None
    if stat.S_ISLNK(selected.st_mode) or not stat.S_ISREG(selected.st_mode):
        raise _invalid_service_file()
    return selected.st_dev, selected.st_ino


def _capture_selected_identity(
    path: Path,
    expected_parent_identity: tuple[int, int],
) -> tuple[int, int]:
    """Bind the construction-time regular file selected inside its parent directory."""
    parent_descriptor = _open_selected_parent(path.parent, expected_parent_identity)
    primary_error: BaseException | None = None
    try:
        return _selected_regular_file_identity(path.name, parent_descriptor)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        _close_descriptor(
            parent_descriptor,
            preserve_primary_error=primary_error is not None,
        )


def _read_bounded_utf8_at(
    file_name: str,
    parent_descriptor: int,
    expected_selected_identity: tuple[int, int],
) -> str:
    """Read the retained regular service file from an authenticated parent descriptor."""
    selected_identity = _selected_regular_file_identity(file_name, parent_descriptor)
    if selected_identity != expected_selected_identity:
        raise _invalid_service_file()

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(file_name, flags, dir_fd=parent_descriptor)
    except (OSError, ValueError, NotImplementedError):
        raise _invalid_service_file() from None

    primary_error: BaseException | None = None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_dev, before.st_ino) != expected_selected_identity
        ):
            raise _invalid_service_file()
        before_snapshot = _service_file_snapshot(before)

        chunks: list[bytes] = []
        remaining = _MAX_SERVICE_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)

        after = os.fstat(descriptor)
        if (
            _service_file_snapshot(after) != before_snapshot
            or len(payload) != after.st_size
        ):
            raise _invalid_service_file()
    except Pg8000CandidateInvalidConninfoError as exc:
        primary_error = exc
        raise
    except (OSError, ValueError) as exc:
        primary_error = exc
        raise _invalid_service_file() from None
    finally:
        _close_descriptor(
            descriptor,
            preserve_primary_error=primary_error is not None,
        )

    if len(payload) > _MAX_SERVICE_FILE_BYTES:
        raise _invalid_service_file()
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise _invalid_service_file() from None
    if "\x00" in text:
        raise _invalid_service_file()
    return text


def _read_bounded_utf8(
    path: Path,
    expected_parent_identity: tuple[int, int],
    expected_selected_identity: tuple[int, int],
) -> str:
    """Read service bytes through retained parent and final-file identities."""
    parent_descriptor = _open_selected_parent(path.parent, expected_parent_identity)
    primary_error: BaseException | None = None
    try:
        return _read_bounded_utf8_at(
            path.name,
            parent_descriptor,
            expected_selected_identity,
        )
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        _close_descriptor(
            parent_descriptor,
            preserve_primary_error=primary_error is not None,
        )


class Pg8000CandidateServiceFileResolver:
    """Resolve one service stanza from an explicit local service-file capability.

    ``service_file`` is selected by the caller and retained as a concrete path;
    relative paths are converted to absolute paths at construction, before any
    later working-directory change can alter their referent. The parent directory
    and selected regular-file identities are also captured at construction.
    Resolution reopens and authenticates that exact directory, requires the final
    component to remain the selected inode, then performs metadata/open operations
    relative to the retained directory descriptor. Replacing the pathname with a
    different regular file therefore requires constructing a new resolver. This
    object never discovers user/system files and never reads environment variables.
    Duplicate section/key authority and malformed target lines fail closed.
    Non-target stanza contents are not promoted into the selected connection
    parameters.
    """

    def __init__(self, service_file: Path) -> None:
        """Retain caller-selected path, parent identity, and final-file identity."""
        if not isinstance(service_file, Path):
            raise _invalid_service_file()
        self._service_file = service_file.absolute()
        self._parent_identity = _capture_parent_identity(self._service_file.parent)
        self._selected_identity = _capture_selected_identity(
            self._service_file,
            self._parent_identity,
        )

    def __call__(self, service_name: str) -> dict[str, str]:
        """Return the exact target stanza or fail without reflecting file content."""
        target = _validate_service_name(service_name)
        text = _read_bounded_utf8(
            self._service_file,
            self._parent_identity,
            self._selected_identity,
        )
        sections: set[str] = set()
        target_found = False
        target_active = False
        parameters: dict[str, str] = {}

        for raw_line in text.splitlines():
            if _has_disallowed_control(raw_line):
                raise _invalid_service_file()
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("["):
                if (
                    not stripped.endswith("]")
                    or stripped.count("[") != 1
                    or stripped.count("]") != 1
                ):
                    raise _invalid_service_file()
                section_name = stripped[1:-1].strip()
                if (
                    not section_name
                    or _has_disallowed_control(section_name)
                    or section_name in sections
                ):
                    raise _invalid_service_file()
                sections.add(section_name)
                target_active = section_name == target
                if target_active:
                    target_found = True
                continue

            if not target_active:
                continue
            if stripped.lower().startswith("ldap://"):
                raise _invalid_service_file(unsupported=True)
            if "=" not in stripped:
                raise _invalid_service_file()
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (
                not key
                or _has_disallowed_control(key)
                or _has_disallowed_control(value)
                or key in parameters
            ):
                raise _invalid_service_file()
            parameters[key] = value

        if not target_found:
            raise _invalid_service_file()
        return parameters
