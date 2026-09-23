# SPDX-License-Identifier: Apache-2.0
"""Regression contract for unique wheel archive-member authority."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
import warnings
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


def _record_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return digest.decode("ascii")


def _wheel_with_duplicate_member() -> bytes:
    """Return a bounded wheel with two conflicting entries for one member name."""
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
    shadowed_payload = b"__version__ = 'shadowed'\n"
    recorded_payload = b"__version__ = '0.1.0'\n"
    rows = [
        f"{PACKAGE_MEMBER},sha256={_record_digest(recorded_payload)},{len(recorded_payload)}",
        f"{metadata_name},sha256={_record_digest(metadata)},{len(metadata)}",
        f"{wheel_name},sha256={_record_digest(wheel_metadata)},{len(wheel_metadata)}",
        f"{record_name},,",
    ]
    record = ("\n".join(rows) + "\n").encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        entries = (
            (PACKAGE_MEMBER, shadowed_payload),
            (metadata_name, metadata),
            (wheel_name, wheel_metadata),
            (PACKAGE_MEMBER, recorded_payload),
            (record_name, record),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, payload in entries:
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_STORED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, payload)
    return output.getvalue()


def test_release_verifier_rejects_duplicate_wheel_member_names(tmp_path: Path) -> None:
    """Reject duplicate ZIP names even when RECORD matches the visible entry."""
    sdist_bytes = _matching_sdist()
    wheel_bytes = _wheel_with_duplicate_member()
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
