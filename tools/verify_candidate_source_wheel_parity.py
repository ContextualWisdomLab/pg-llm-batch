#!/usr/bin/env python3
"""Verify executable pg8000 sources agree between pinned sdist and wheel artifacts.

PyPI publishes pg8000 1.31.5 as both a source distribution and a universal wheel,
but the release was uploaded without Trusted Publishing. The repository already
pins and license-checks the wheel used for candidate execution. This verifier
adds an independent, non-executing artifact-consistency check: every Python
source shipped under the pg8000 package in the exact wheel must have the same
path and bytes in the exact source distribution, and neither artifact may add a
Python module absent from the other.

The verifier never extracts archives, imports candidate code, follows archive
links, or accepts alternate artifact names. Finite member, file-count, and total
payload limits keep malformed archives from turning provenance inspection into an
unbounded resource operation.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile


_EXPECTED_SDIST_NAME = "pg8000-1.31.5.tar.gz"
_EXPECTED_WHEEL_NAME = "pg8000-1.31.5-py3-none-any.whl"
_SDIST_PACKAGE_PREFIX = "pg8000-1.31.5/src/pg8000/"
_WHEEL_PACKAGE_PREFIX = "pg8000/"
_MAX_PACKAGE_FILES = 512
_MAX_MEMBER_BYTES = 2 * 1024 * 1024
_MAX_PACKAGE_BYTES = 8 * 1024 * 1024


class CandidateSourceWheelParityError(RuntimeError):
    """Reject candidate artifacts that cannot prove source-to-wheel parity."""


def _relative_python_path(member_name: str, *, prefix: str) -> str | None:
    """Return one bounded package-relative Python path or ``None`` for other files."""
    if not member_name.startswith(prefix):
        return None
    relative = member_name[len(prefix) :]
    if not relative or relative.endswith("/") or not relative.endswith(".py"):
        return None
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CandidateSourceWheelParityError("candidate package member path is invalid")
    return path.as_posix()


def _record_payload(
    payloads: dict[str, str],
    *,
    relative_path: str,
    payload: bytes,
    total_bytes: int,
) -> int:
    """Record one source digest while enforcing finite and unique package evidence."""
    if len(payload) > _MAX_MEMBER_BYTES:
        raise CandidateSourceWheelParityError("candidate package member exceeds size limit")
    if relative_path in payloads:
        raise CandidateSourceWheelParityError("candidate package member identity is duplicated")
    if len(payloads) >= _MAX_PACKAGE_FILES:
        raise CandidateSourceWheelParityError("candidate package file count exceeds limit")
    total_bytes += len(payload)
    if total_bytes > _MAX_PACKAGE_BYTES:
        raise CandidateSourceWheelParityError("candidate package payload exceeds size limit")
    payloads[relative_path] = sha256(payload).hexdigest()
    return total_bytes


def _sdist_python_payloads(sdist_path: Path) -> dict[str, str]:
    """Read bounded Python-source digests from the exact pg8000 source distribution."""
    if sdist_path.name != _EXPECTED_SDIST_NAME or not sdist_path.is_file():
        raise CandidateSourceWheelParityError("candidate source artifact identity is invalid")

    payloads: dict[str, str] = {}
    total_bytes = 0
    try:
        with tarfile.open(sdist_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                relative = _relative_python_path(
                    member.name,
                    prefix=_SDIST_PACKAGE_PREFIX,
                )
                if relative is None:
                    continue
                if not member.isfile():
                    raise CandidateSourceWheelParityError(
                        "candidate source package member is not a regular file"
                    )
                if member.size < 0 or member.size > _MAX_MEMBER_BYTES:
                    raise CandidateSourceWheelParityError(
                        "candidate package member exceeds size limit"
                    )
                stream = archive.extractfile(member)
                if stream is None:
                    raise CandidateSourceWheelParityError(
                        "candidate source package member could not be inspected"
                    )
                payload = stream.read(_MAX_MEMBER_BYTES + 1)
                if len(payload) != member.size:
                    raise CandidateSourceWheelParityError(
                        "candidate source package member size is inconsistent"
                    )
                total_bytes = _record_payload(
                    payloads,
                    relative_path=relative,
                    payload=payload,
                    total_bytes=total_bytes,
                )
    except CandidateSourceWheelParityError:
        raise
    except (OSError, tarfile.TarError, EOFError):
        raise CandidateSourceWheelParityError(
            "candidate source artifact could not be inspected"
        ) from None

    if not payloads:
        raise CandidateSourceWheelParityError("candidate source package payload is empty")
    return payloads


def _wheel_python_payloads(wheel_path: Path) -> dict[str, str]:
    """Read bounded Python-source digests from the exact pg8000 universal wheel."""
    if wheel_path.name != _EXPECTED_WHEEL_NAME or not wheel_path.is_file():
        raise CandidateSourceWheelParityError("candidate wheel artifact identity is invalid")

    payloads: dict[str, str] = {}
    total_bytes = 0
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            for member in archive.infolist():
                relative = _relative_python_path(
                    member.filename,
                    prefix=_WHEEL_PACKAGE_PREFIX,
                )
                if relative is None:
                    continue
                if member.is_dir() or member.file_size > _MAX_MEMBER_BYTES:
                    raise CandidateSourceWheelParityError(
                        "candidate package member exceeds size limit"
                    )
                payload = archive.read(member)
                if len(payload) != member.file_size:
                    raise CandidateSourceWheelParityError(
                        "candidate wheel package member size is inconsistent"
                    )
                total_bytes = _record_payload(
                    payloads,
                    relative_path=relative,
                    payload=payload,
                    total_bytes=total_bytes,
                )
    except CandidateSourceWheelParityError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
        raise CandidateSourceWheelParityError(
            "candidate wheel artifact could not be inspected"
        ) from None

    if not payloads:
        raise CandidateSourceWheelParityError("candidate wheel package payload is empty")
    return payloads


def verify_candidate_source_wheel_parity(sdist_path: Path, wheel_path: Path) -> None:
    """Require exact Python package path and byte parity across pinned artifacts."""
    if not isinstance(sdist_path, Path) or not isinstance(wheel_path, Path):
        raise CandidateSourceWheelParityError("candidate artifact path is invalid")
    source_payloads = _sdist_python_payloads(sdist_path)
    wheel_payloads = _wheel_python_payloads(wheel_path)
    if source_payloads != wheel_payloads:
        raise CandidateSourceWheelParityError("candidate source and wheel package payload differs")


def main(argv: list[str] | None = None) -> int:
    """Run source-to-wheel parity verification for one exact pg8000 candidate pair."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        raise SystemExit(
            "usage: verify_candidate_source_wheel_parity.py SDIST_PATH WHEEL_PATH"
        )
    try:
        verify_candidate_source_wheel_parity(Path(arguments[0]), Path(arguments[1]))
    except CandidateSourceWheelParityError as exc:
        raise SystemExit(str(exc)) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
