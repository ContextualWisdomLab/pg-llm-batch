# SPDX-License-Identifier: Apache-2.0
"""Regression contract for safe source-distribution archive-member paths."""

from __future__ import annotations

import base64
import hashlib
import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


DISTRIBUTION = "pg-llm-batch"
VERSION = "0.1.0"
WHEEL = "pg_llm_batch-0.1.0-py3-none-any.whl"
SDIST = "pg_llm_batch-0.1.0.tar.gz"
TOP_LEVEL = "pg_llm_batch-0.1.0"
DIST_INFO = "pg_llm_batch-0.1.0.dist-info"
PACKAGE_MEMBER = "pg_llm_batch/__init__.py"
UNSAFE_MEMBERS = ("../escape.py", f"{TOP_LEVEL}/../../escape.py")
CORE_METADATA = (
    b"Metadata-Version: 2.4\n"
    b"Name: pg-llm-batch\n"
    b"Version: 0.1.0\n"
    b"Summary: release evidence\n\n"
)


def _add_regular_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    member.mtime = 0
    archive.addfile(member, io.BytesIO(payload))


def _sdist_with_unsafe_member(member_name: str) -> bytes:
    """Return a bounded sdist with one member that escapes its extraction root."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        _add_regular_member(archive, f"{TOP_LEVEL}/PKG-INFO", CORE_METADATA)
        _add_regular_member(
            archive,
            f"{TOP_LEVEL}/pyproject.toml",
            b"[build-system]\nrequires = []\n",
        )
        _add_regular_member(
            archive,
            member_name,
            b"raise RuntimeError('must never escape the sdist extraction root')\n",
        )
    return output.getvalue()


def _urlsafe_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return digest.decode("ascii")


def _matching_wheel() -> bytes:
    """Return one bounded wheel whose metadata agrees with release authority."""
    metadata_name = f"{DIST_INFO}/METADATA"
    wheel_name = f"{DIST_INFO}/WHEEL"
    record_name = f"{DIST_INFO}/RECORD"
    wheel_metadata = (
        b"Wheel-Version: 1.0\n"
        b"Generator: pg-llm-batch-test\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n\n"
    )
    payloads = (
        (PACKAGE_MEMBER, b"__version__ = '0.1.0'\n"),
        (metadata_name, CORE_METADATA),
        (wheel_name, wheel_metadata),
    )
    rows = [
        f"{path},sha256={_urlsafe_digest(payload)},{len(payload)}"
        for path, payload in payloads
    ]
    rows.append(f"{record_name},,")
    record = ("\n".join(rows) + "\n").encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for path, payload in (*payloads, (record_name, record)):
            entry = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry, payload)
    return output.getvalue()


@pytest.mark.parametrize("unsafe_member", UNSAFE_MEMBERS)
def test_release_verifier_rejects_sdist_members_outside_extraction_root(
    tmp_path: Path,
    unsafe_member: str,
) -> None:
    """Reject reproducible sdists containing members that escape the destination."""
    sdist_bytes = _sdist_with_unsafe_member(unsafe_member)
    wheel_bytes = _matching_wheel()
    for directory_name in ("first", "second"):
        directory = tmp_path / directory_name
        directory.mkdir()
        (directory / SDIST).write_bytes(sdist_bytes)
        (directory / WHEEL).write_bytes(wheel_bytes)

    with pytest.raises(
        ReleaseEvidenceError,
        match="release artifact metadata does not match release authority",
    ):
        verify_reproducible_release(
            tmp_path / "first",
            tmp_path / "second",
            distribution_name=DISTRIBUTION,
            version=VERSION,
            source_commit="a" * 40,
            source_date_epoch=1,
        )
