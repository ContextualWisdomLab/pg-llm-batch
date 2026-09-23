# SPDX-License-Identifier: Apache-2.0
"""Regression contract for wheel License-File payload authority."""

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
LICENSE_PATH = "LICENSE.txt"
LICENSE_PAYLOAD = b"Apache License 2.0 test fixture\n"
CORE_METADATA = (
    b"Metadata-Version: 2.4\n"
    b"Name: pg-llm-batch\n"
    b"Version: 0.1.0\n"
    b"License-Expression: Apache-2.0\n"
    b"License-File: LICENSE.txt\n\n"
)


def _add_regular_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    member.mtime = 0
    archive.addfile(member, io.BytesIO(payload))


def _matching_sdist() -> bytes:
    """Return a bounded sdist with the declared license payload present."""
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
            f"{TOP_LEVEL}/{LICENSE_PATH}",
            LICENSE_PAYLOAD,
        )
    return output.getvalue()


def _urlsafe_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return digest.decode("ascii")


def _wheel_with_invalid_license_location(license_member: str | None) -> bytes:
    """Return a canonical wheel except for its declared license-file payload."""
    metadata_name = f"{DIST_INFO}/METADATA"
    wheel_name = f"{DIST_INFO}/WHEEL"
    record_name = f"{DIST_INFO}/RECORD"
    wheel_metadata = (
        b"Wheel-Version: 1.0\n"
        b"Generator: pg-llm-batch-test\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n\n"
    )
    package_payload = b"__version__ = '0.1.0'\n"
    payloads: list[tuple[str, bytes]] = [
        (PACKAGE_MEMBER, package_payload),
        (metadata_name, CORE_METADATA),
        (wheel_name, wheel_metadata),
    ]
    if license_member is not None:
        payloads.append((license_member, LICENSE_PAYLOAD))

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


@pytest.mark.parametrize(
    "license_member",
    (
        None,
        f"{DIST_INFO}/{LICENSE_PATH}",
    ),
    ids=("missing-declared-license", "license-outside-licenses-directory"),
)
def test_release_verifier_binds_wheel_license_file_to_metadata_authority(
    tmp_path: Path,
    license_member: str | None,
) -> None:
    """Reject a declared wheel license file that is absent from its required path."""
    sdist_bytes = _matching_sdist()
    wheel_bytes = _wheel_with_invalid_license_location(license_member)
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
