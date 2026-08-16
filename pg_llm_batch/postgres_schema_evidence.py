# SPDX-License-Identifier: Apache-2.0
"""Derive bounded content-free integrity evidence for the packaged PostgreSQL schema."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# Package metadata requires Python >=3.10, so this stdlib import is supported.
from importlib import resources  # nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
from typing import BinaryIO


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_SCHEMA_BYTES = 16 * 1024 * 1024
_SCHEMA_PACKAGE = "pg_llm_batch"
_SCHEMA_RESOURCE = "schema.sql"


class PostgresSchemaEvidenceError(ValueError):
    """Report a fail-closed packaged PostgreSQL schema evidence violation."""


@dataclass(frozen=True, slots=True)
class PostgresSchemaEvidence:
    """Represent content-free integrity evidence for the packaged schema bytes."""

    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable packaged schema evidence schema."""
        return {"sha256": self.sha256, "size_bytes": self.size_bytes}


def _open_schema_resource() -> BinaryIO:
    """Open the package-owned schema resource without exposing resource diagnostics."""
    try:
        return resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_RESOURCE).open("rb")
    except Exception:
        # Import-resource loaders may surface ordinary exceptions outside the
        # OSError family (for example a corrupt archive). Keep every such
        # lower-layer diagnostic outside the stable recovery-evidence boundary
        # while allowing BaseException control flow to propagate normally.
        raise PostgresSchemaEvidenceError(
            "PostgreSQL package schema could not be opened"
        ) from None


def _quiet_close(stream: BinaryIO) -> None:
    """Attempt cleanup without replacing an already-selected bounded error."""
    try:
        stream.close()
    except Exception:
        # Cleanup is best effort only after a primary bounded failure has been
        # selected. Ordinary stream-state/importer exceptions must not mask it.
        pass


def _close_schema_stream(stream: BinaryIO) -> None:
    """Close one schema stream or raise a fixed content-free cleanup error."""
    try:
        stream.close()
    except Exception:
        raise PostgresSchemaEvidenceError(
            "PostgreSQL package schema stream could not be closed"
        ) from None


def inspect_postgres_schema() -> PostgresSchemaEvidence:
    """Hash the exact packaged schema bytes with a finite package-owned work budget."""
    stream = _open_schema_resource()
    try:
        digest = hashlib.sha256()
        size_bytes = 0
        while True:
            try:
                chunk = stream.read(_HASH_CHUNK_BYTES)
            except Exception:
                # A packaged archive/resource reader can fail with ordinary
                # exceptions that are not OSError subclasses. Normalize them
                # before they can become operator or recovery-receipt evidence.
                raise PostgresSchemaEvidenceError(
                    "PostgreSQL package schema could not be read"
                ) from None
            if type(chunk) is not bytes:
                # Binary package streams must return exact built-in bytes. Refuse
                # subclasses and alternate buffer types before truthiness, len,
                # or hashing can invoke behavior outside the evidence boundary.
                raise PostgresSchemaEvidenceError(
                    "PostgreSQL package schema could not be read"
                )
            if not chunk:
                break
            size_bytes += len(chunk)
            if size_bytes > _MAX_SCHEMA_BYTES:
                raise PostgresSchemaEvidenceError(
                    "PostgreSQL package schema must have a positive bounded size"
                )
            digest.update(chunk)

        if size_bytes == 0:
            raise PostgresSchemaEvidenceError(
                "PostgreSQL package schema must have a positive bounded size"
            )
        evidence = PostgresSchemaEvidence(
            sha256=digest.hexdigest(),
            size_bytes=size_bytes,
        )
    except BaseException:
        _quiet_close(stream)
        raise

    _close_schema_stream(stream)
    return evidence
