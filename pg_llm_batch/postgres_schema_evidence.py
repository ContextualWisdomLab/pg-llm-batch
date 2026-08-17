# SPDX-License-Identifier: Apache-2.0
"""Derive bounded content-free integrity evidence for the packaged PostgreSQL schema."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# Package metadata requires Python >=3.10, so this stdlib import is supported.
from importlib import resources  # nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
from typing import BinaryIO
from weakref import ReferenceType, ref


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_SCHEMA_BYTES = 16 * 1024 * 1024
_SCHEMA_PACKAGE = "pg_llm_batch"
_SCHEMA_RESOURCE = "schema.sql"
_SCHEMA_INSPECTION_MARK = object()
_INSPECTED_SCHEMA_EVIDENCE_IDS: dict[
    int, tuple[ReferenceType[PostgresSchemaEvidence], str, int]
] = {}


class PostgresSchemaEvidenceError(ValueError):
    """Report a fail-closed packaged PostgreSQL schema evidence violation."""


@dataclass(frozen=True)
class PostgresSchemaEvidence:
    """Represent content-free integrity evidence for the packaged schema bytes."""

    sha256: str
    size_bytes: int
    _inspection_mark: object = field(default=None, repr=False, compare=False)

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable packaged schema evidence schema."""
        return {"sha256": self.sha256, "size_bytes": self.size_bytes}


def _record_inspected_schema_evidence(evidence: PostgresSchemaEvidence) -> None:
    """Remember a live inspected object and its immutable observed field snapshot."""
    evidence_id = id(evidence)

    def discard(collected: ReferenceType[PostgresSchemaEvidence]) -> None:
        """Remove only the registry entry that owns this collected weak reference."""
        current = _INSPECTED_SCHEMA_EVIDENCE_IDS.get(evidence_id)
        if current is not None and current[0] is collected:
            _INSPECTED_SCHEMA_EVIDENCE_IDS.pop(evidence_id, None)

    evidence_reference = ref(evidence, discard)
    _INSPECTED_SCHEMA_EVIDENCE_IDS[evidence_id] = (
        evidence_reference,
        evidence.sha256,
        evidence.size_bytes,
    )


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
            # Read no more than the remaining hashing budget plus one sentinel
            # byte. The sentinel distinguishes an exactly-at-budget schema from
            # a compromised oversized resource without allowing a full chunk of
            # work beyond the package-owned ceiling.
            remaining_probe_bytes = _MAX_SCHEMA_BYTES - size_bytes + 1
            try:
                chunk = stream.read(
                    min(_HASH_CHUNK_BYTES, remaining_probe_bytes)
                )
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
            _inspection_mark=_SCHEMA_INSPECTION_MARK,
        )
    except BaseException:
        _quiet_close(stream)
        raise

    _close_schema_stream(stream)
    _record_inspected_schema_evidence(evidence)
    return evidence


def postgres_schema_evidence_was_inspected(evidence: object) -> bool:
    """Return whether a live exact object still matches its observed inspection fields."""
    if type(evidence) is not PostgresSchemaEvidence:
        return False
    observed = _INSPECTED_SCHEMA_EVIDENCE_IDS.get(id(evidence))
    if observed is None:
        return False
    evidence_reference, observed_sha256, observed_size_bytes = observed
    return (
        evidence_reference() is evidence
        and evidence._inspection_mark is _SCHEMA_INSPECTION_MARK
        and type(evidence.sha256) is str
        and type(evidence.size_bytes) is int
        and evidence.sha256 == observed_sha256
        and evidence.size_bytes == observed_size_bytes
    )
