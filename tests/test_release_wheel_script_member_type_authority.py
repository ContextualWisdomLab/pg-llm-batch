# SPDX-License-Identifier: Apache-2.0
"""Regression contract for regular-file-only wheel script members."""

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
DATA_ROOT = "pg_llm_batch-0.1.0.data"
PACKAGE_MEMBER = "pg_llm_batch/__init__.py"
SCRIPT_MEMBER = f"{DATA_ROOT}/scripts/pg-llm-batch"


def _add_regular_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    member.mtime = 0
    archive.addfile(member, io.BytesIO(payload))


def _matching_sdist() -> bytes:
    """Return one bounded sdist whose identity agrees with release authority."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        _add_regular_member(
            archive,
            f"{TOP_LEVEL}/PKG-INFO",
            b"Metadata-Version: 2.4\nName: pg-llm-batch\nVersion: 0.1.0\n\n",
        )
        _add_regular_member(
            archive,
            f"{TOP_LEVEL}/pyproject.toml",
            b"[build-system]\nrequires = []\n",
        )
    return output.getvalue()


def _urlsafe_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return digest.decode("ascii")


def _wheel_with_script_symlink() -> bytes:
    """Return a canonical wheel except for one non-regular scripts member."""
    metadata_name = f"{DIST_INFO}/METADATA"
    wheel_name = f"{DIST_INFO}/WHEEL"
    record_name = f"{DIST_INFO}/RECORD"
    metadata = b"Metadata-Version: 2.4\nName: pg-llm-batch\nVersion: 0.1.0\n\n"
    wheel_metadata = (
        b"Wheel-Version: 1.0\n"
        b"Generator: pg-llm-batch-test\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n\n"
    )
    package_payload = b"__version__ = '0.1.0'\n"
    script_payload = b"../pg_llm_batch/__init__.py"
    regular_payloads = (
        (PACKAGE_MEMBER, package_payload),
        (metadata_name, metadata),
        (wheel_name, wheel_metadata),
    )
    rows = [
        f"{path},sha256={_urlsafe_digest(payload)},{len(payload)}"
        for path, payload in (*regular_payloads, (SCRIPT_MEMBER, script_payload))
    ]
    rows.append(f"{record_name},,")
    record = ("\n".join(rows) + "\n").encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for path, payload in regular_payloads:
            entry = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry, payload)

        script_entry = zipfile.ZipInfo(
            SCRIPT_MEMBER,
            date_time=(1980, 1, 1, 0, 0, 0),
        )
        script_entry.compress_type = zipfile.ZIP_STORED
        script_entry.create_system = 3
        script_entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(script_entry, script_payload)

        record_entry = zipfile.ZipInfo(
            record_name,
            date_time=(1980, 1, 1, 0, 0, 0),
        )
        record_entry.compress_type = zipfile.ZIP_STORED
        record_entry.create_system = 3
        record_entry.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(record_entry, record)
    return output.getvalue()


def test_release_verifier_rejects_non_regular_wheel_script_member(
    tmp_path: Path,
) -> None:
    """Reject wheel scripts represented by symlinks instead of regular files."""
    sdist_bytes = _matching_sdist()
    wheel_bytes = _wheel_with_script_symlink()
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
