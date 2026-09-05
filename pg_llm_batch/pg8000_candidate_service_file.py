"""Bounded caller-selected ``pg_service.conf`` resolver for the pg8000 candidate.

PostgreSQL service files are an INI-like indirection from a service name to
connection parameters. pg8000 does not implement libpq's service-file lookup,
and the database driver must not silently acquire process-environment or
filesystem-discovery authority while pg-llm-batch evaluates a replacement for
Psycopg. This candidate resolver therefore reads exactly one caller-selected
file, applies a finite byte budget, and returns only the exact target stanza.

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


def _read_bounded_utf8(path: Path) -> str:
    """Read one explicit regular service file under a finite UTF-8 byte budget.

    The caller-selected path is opened nonblocking where the platform supports
    it, then the retained descriptor is required to name one stable regular
    file before and after the bounded read. This prevents a FIFO/device path or
    in-place mutation from becoming connection-selector authority while bytes
    are being inspected.
    """
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError):
        raise _invalid_service_file() from None

    primary_error: BaseException | None = None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
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
        try:
            os.close(descriptor)
        except OSError:
            if primary_error is None:
                raise _invalid_service_file() from None

    if len(payload) > _MAX_SERVICE_FILE_BYTES:
        raise _invalid_service_file()
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise _invalid_service_file() from None
    if "\x00" in text:
        raise _invalid_service_file()
    return text


class Pg8000CandidateServiceFileResolver:
    """Resolve one service stanza from an explicit local service-file capability.

    ``service_file`` is selected by the caller and retained as a concrete path;
    this object never discovers user/system files and never reads environment
    variables. Duplicate section/key authority and malformed target lines fail
    closed. Non-target stanza contents are not promoted into the selected
    connection parameters.
    """

    def __init__(self, service_file: Path) -> None:
        """Retain exactly one caller-selected service file after validating its path type."""
        if not isinstance(service_file, Path):
            raise _invalid_service_file()
        self._service_file = service_file

    def __call__(self, service_name: str) -> dict[str, str]:
        """Return the exact target stanza or fail without reflecting file content."""
        target = _validate_service_name(service_name)
        text = _read_bounded_utf8(self._service_file)
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
