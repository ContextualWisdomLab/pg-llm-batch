# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Bounded incremental retrieval for provider result and error JSONL files."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from .batch_api_client import (
    DOWNLOAD_CHUNK_BYTES,
    BatchAPIClient,
    _validate_resource_id,
)
from .db import validate_endpoint_alias
from .exceptions import GatewayError, ValidationError

DEFAULT_MAX_JSONL_LINE_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_JSONL_RECORDS = 100_000
DEFAULT_MAX_JSONL_PHYSICAL_LINES = 100_000
CHECKPOINT_SCHEMA_VERSION = 1
_CHECKPOINT_DOMAIN = b"pg-llm-batch/result-checkpoint/v1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class BatchResultRecord:
    """One incrementally decoded provider result or error record.

    Attributes:
        batch_id: Validated provider batch identifier associated with the record.
        file_kind: Stable ``result`` or ``error`` classification.
        record: Decoded JSON object from one provider-controlled JSONL line.
    """

    batch_id: str
    file_kind: str
    record: Dict[str, Any]


def _checkpoint_validation_error(field: str, value: Any, reason: str) -> ValidationError:
    """Build one structured validation failure for a checkpoint field."""
    return ValidationError(field=field, value=value, reason=reason)


def _strict_positive_integer(field: str, value: Any) -> int:
    """Require one non-coercive positive integer checkpoint field."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _checkpoint_validation_error(field, value, "must be a positive integer")
    return value


@dataclass(frozen=True)
class BatchResultCheckpoint:
    """Host-persistable evidence for one acknowledged streaming record.

    The checkpoint binds the validated request identity, provider file identity,
    physical and logical positions, and a SHA-256 digest of the complete bounded
    physical stream prefix through this record. It detects changed replay input;
    it is not an authentication credential or a substitute for protecting the
    host's durable checkpoint store.
    """

    schema_version: int
    batch_id: str
    endpoint_alias: str
    file_kind: str
    file_id: str
    file_line_number: int
    batch_line_count: int
    record_count: int
    prefix_sha256: str

    def __post_init__(self) -> None:
        """Validate every persisted field without trimming or coercion."""
        if (
            isinstance(self.schema_version, bool)
            or self.schema_version != CHECKPOINT_SCHEMA_VERSION
        ):
            raise _checkpoint_validation_error(
                "schema_version",
                self.schema_version,
                f"must be the integer {CHECKPOINT_SCHEMA_VERSION}",
            )
        try:
            _validate_resource_id(self.batch_id, "batch_id")
        except ValidationError as exc:
            raise _checkpoint_validation_error(
                "batch_id", self.batch_id, "must be a supported provider identifier"
            ) from exc
        normalized_alias = validate_endpoint_alias(self.endpoint_alias)
        if normalized_alias != self.endpoint_alias:
            raise _checkpoint_validation_error(
                "endpoint_alias",
                self.endpoint_alias,
                "must already be normalized without surrounding whitespace",
            )
        if self.file_kind not in {"result", "error"}:
            raise _checkpoint_validation_error(
                "file_kind", self.file_kind, "must be 'result' or 'error'"
            )
        try:
            _validate_resource_id(self.file_id, "file_id")
        except ValidationError as exc:
            raise _checkpoint_validation_error(
                "file_id", self.file_id, "must be a supported provider identifier"
            ) from exc
        file_line_number = _strict_positive_integer(
            "file_line_number", self.file_line_number
        )
        batch_line_count = _strict_positive_integer(
            "batch_line_count", self.batch_line_count
        )
        record_count = _strict_positive_integer("record_count", self.record_count)
        if batch_line_count < file_line_number:
            raise _checkpoint_validation_error(
                "batch_line_count",
                self.batch_line_count,
                "must be greater than or equal to file_line_number",
            )
        if record_count > batch_line_count:
            raise _checkpoint_validation_error(
                "record_count",
                self.record_count,
                "must not exceed batch_line_count",
            )
        if (
            not isinstance(self.prefix_sha256, str)
            or _SHA256_PATTERN.fullmatch(self.prefix_sha256) is None
        ):
            raise _checkpoint_validation_error(
                "prefix_sha256",
                self.prefix_sha256,
                "must be exactly 64 lowercase hexadecimal characters",
            )


@dataclass(frozen=True)
class CheckpointedBatchResultRecord:
    """One decoded record paired with its exact resumable checkpoint."""

    batch_id: str
    file_kind: str
    record: Dict[str, Any]
    checkpoint: BatchResultCheckpoint


@dataclass
class _PhysicalLineBudget:
    """Track one batch-wide physical JSONL line processing ceiling."""

    limit: int
    observed: int = 0

    def observe(self, *, file_kind: str, file_line_number: int) -> None:
        """Record one physical line and fail before parsing above the ceiling."""
        self.observed += 1
        if self.observed > self.limit:
            raise GatewayError(
                "Provider JSONL physical line limit exceeded",
                response_data={
                    "file_kind": file_kind,
                    "file_line_number": file_line_number,
                    "batch_line_count": self.observed,
                    "limit_lines": self.limit,
                },
            )


@dataclass(frozen=True)
class _PhysicalJsonlLine:
    """One bounded physical line and its optional decoded JSON object."""

    file_line_number: int
    raw_line: bytes
    newline_terminated: bool
    record: Optional[Dict[str, Any]]


def _validate_positive_integer(field: str, value: Any) -> int:
    """Require one strict positive integer resource limit."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(
            field=field,
            value=value,
            reason="must be a positive integer",
        )
    return value


def _reject_non_finite_json_constant(constant: str) -> None:
    """Reject JSON extensions such as NaN and infinity values."""
    raise ValueError(f"non-finite JSON number is not permitted: {constant}")


def _object_without_duplicate_names(
    pairs: list[tuple[str, Any]],
) -> Dict[str, Any]:
    """Build one JSON object while rejecting ambiguous duplicate names."""
    result: Dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON object name")
        result[name] = value
    return result


def _checkpoint_frame(hasher: Any, tag: bytes, payload: bytes) -> None:
    """Append one unambiguous length-prefixed field to a checkpoint digest."""
    hasher.update(len(tag).to_bytes(2, "big"))
    hasher.update(tag)
    hasher.update(len(payload).to_bytes(8, "big"))
    hasher.update(payload)


def _new_checkpoint_hasher(batch_id: str, endpoint_alias: str) -> Any:
    """Create one domain-separated SHA-256 prefix hasher."""
    hasher = hashlib.sha256()
    _checkpoint_frame(hasher, b"domain", _CHECKPOINT_DOMAIN)
    _checkpoint_frame(hasher, b"batch_id", batch_id.encode("utf-8"))
    _checkpoint_frame(hasher, b"endpoint_alias", endpoint_alias.encode("utf-8"))
    return hasher


def _add_checkpoint_file(
    hasher: Any,
    *,
    file_kind: str,
    file_id: str,
) -> None:
    """Bind one ordered provider file identity to the stream prefix."""
    _checkpoint_frame(hasher, b"file_kind", file_kind.encode("ascii"))
    _checkpoint_frame(hasher, b"file_id", file_id.encode("ascii"))


def _add_checkpoint_line(
    hasher: Any,
    *,
    file_line_number: int,
    raw_line: bytes,
    newline_terminated: bool,
) -> None:
    """Bind one exact physical line and its termination state to the prefix."""
    _checkpoint_frame(
        hasher,
        b"file_line_number",
        file_line_number.to_bytes(8, "big"),
    )
    _checkpoint_frame(hasher, b"line_bytes", raw_line)
    _checkpoint_frame(
        hasher,
        b"newline_terminated",
        b"\x01" if newline_terminated else b"\x00",
    )


class StreamingBatchAPIClient(BatchAPIClient):
    """Batch client that yields provider JSONL records without whole-body storage.

    This opt-in client preserves :class:`BatchAPIClient` HTTP, credential, retry,
    redirect, and total-download controls. It additionally limits bytes in one
    unterminated JSONL line, physical lines processed, and records yielded for
    one batch.
    """

    def __init__(
        self,
        postgres_dsn: str,
        credentials: Any,
        *,
        max_jsonl_line_bytes: int = DEFAULT_MAX_JSONL_LINE_BYTES,
        max_jsonl_records: int = DEFAULT_MAX_JSONL_RECORDS,
        max_jsonl_physical_lines: int = DEFAULT_MAX_JSONL_PHYSICAL_LINES,
        **kwargs: Any,
    ) -> None:
        """Initialize bounded incremental JSONL retrieval resources."""
        validated_line_bytes = _validate_positive_integer(
            "max_jsonl_line_bytes", max_jsonl_line_bytes
        )
        validated_records = _validate_positive_integer(
            "max_jsonl_records", max_jsonl_records
        )
        validated_physical_lines = _validate_positive_integer(
            "max_jsonl_physical_lines", max_jsonl_physical_lines
        )
        super().__init__(postgres_dsn, credentials, **kwargs)
        self.max_jsonl_line_bytes = validated_line_bytes
        self.max_jsonl_records = validated_records
        self.max_jsonl_physical_lines = validated_physical_lines

    @asynccontextmanager
    async def open_batch_records(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> AsyncIterator[AsyncIterator[BatchResultRecord]]:
        """Open a record iterator that deterministically closes provider responses.

        Use this context manager when a consumer may stop before exhausting the
        iterator. Leaving the ``async with`` block closes the outer iterator,
        which in turn closes any active provider-file response exactly once.
        """
        records = self.iter_batch_records(batch_id, endpoint_alias)
        try:
            yield records
        finally:
            await records.aclose()

    @asynccontextmanager
    async def open_checkpointed_batch_records(
        self,
        batch_id: str,
        endpoint_alias: str,
        *,
        resume_after: Optional[BatchResultCheckpoint] = None,
    ) -> AsyncIterator[AsyncIterator[CheckpointedBatchResultRecord]]:
        """Open a resumable iterator with deterministic provider-response cleanup."""
        records = self.iter_checkpointed_batch_records(
            batch_id,
            endpoint_alias,
            resume_after=resume_after,
        )
        try:
            yield records
        finally:
            await records.aclose()

    async def iter_batch_records(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> AsyncIterator[BatchResultRecord]:
        """Yield bounded result records followed by bounded provider error records.

        The batch status is retrieved once before file access. Iteration is
        permitted only for a terminal batch that exposes at least one provider
        output or error file identifier. Physical lines from result and error
        files share one batch-wide budget, including blank lines. Consumers that
        may exit early should use :meth:`open_batch_records` so the active
        response closes deterministically.
        """
        validated_batch_id, files = await self._validated_stream_files(
            batch_id,
            endpoint_alias,
        )
        record_count = 0
        physical_line_budget = _PhysicalLineBudget(self.max_jsonl_physical_lines)
        for file_kind, file_id in files:
            if not file_id:
                continue
            async with aclosing(
                self._iter_jsonl_file(
                    file_id,
                    endpoint_alias,
                    file_kind=file_kind,
                    physical_line_budget=physical_line_budget,
                )
            ) as file_records:
                async for record in file_records:
                    record_count += 1
                    self._enforce_record_limit(
                        record_count=record_count,
                        file_kind=file_kind,
                    )
                    yield BatchResultRecord(validated_batch_id, file_kind, record)

    async def iter_checkpointed_batch_records(
        self,
        batch_id: str,
        endpoint_alias: str,
        *,
        resume_after: Optional[BatchResultCheckpoint] = None,
    ) -> AsyncIterator[CheckpointedBatchResultRecord]:
        """Yield records with exact prefix checkpoints and optional safe resume.

        Resume always revalidates the bounded stream from byte zero and yields
        nothing until the supplied checkpoint is reproduced exactly. A changed,
        truncated, or differently framed prefix fails closed before any later
        record is delivered.
        """
        validated_batch_id = _validate_resource_id(batch_id, "batch_id")
        validated_alias = validate_endpoint_alias(endpoint_alias)
        if validated_alias != endpoint_alias:
            raise ValidationError(
                field="endpoint_alias",
                value=endpoint_alias,
                reason="must already be normalized without surrounding whitespace",
            )
        checkpoint = self._validate_resume_checkpoint(
            resume_after,
            batch_id=validated_batch_id,
            endpoint_alias=validated_alias,
        )
        validated_batch_id, files = await self._validated_stream_files(
            validated_batch_id,
            validated_alias,
        )

        hasher = _new_checkpoint_hasher(validated_batch_id, validated_alias)
        physical_line_budget = _PhysicalLineBudget(self.max_jsonl_physical_lines)
        record_count = 0
        checkpoint_matched = checkpoint is None
        for file_kind, file_id in files:
            if not file_id:
                continue
            validated_file_id = _validate_resource_id(
                file_id,
                f"{file_kind}_file_id",
            )
            _add_checkpoint_file(
                hasher,
                file_kind=file_kind,
                file_id=validated_file_id,
            )
            async with aclosing(
                self._iter_jsonl_file_lines(
                    validated_file_id,
                    validated_alias,
                    file_kind=file_kind,
                    physical_line_budget=physical_line_budget,
                )
            ) as physical_lines:
                async for physical_line in physical_lines:
                    _add_checkpoint_line(
                        hasher,
                        file_line_number=physical_line.file_line_number,
                        raw_line=physical_line.raw_line,
                        newline_terminated=physical_line.newline_terminated,
                    )
                    if physical_line.record is None:
                        continue
                    record_count += 1
                    self._enforce_record_limit(
                        record_count=record_count,
                        file_kind=file_kind,
                    )
                    current_checkpoint = BatchResultCheckpoint(
                        schema_version=CHECKPOINT_SCHEMA_VERSION,
                        batch_id=validated_batch_id,
                        endpoint_alias=validated_alias,
                        file_kind=file_kind,
                        file_id=validated_file_id,
                        file_line_number=physical_line.file_line_number,
                        batch_line_count=physical_line_budget.observed,
                        record_count=record_count,
                        prefix_sha256=hasher.copy().hexdigest(),
                    )
                    if not checkpoint_matched:
                        if record_count < checkpoint.record_count:
                            continue
                        if current_checkpoint != checkpoint:
                            raise self._checkpoint_mismatch_error(
                                checkpoint,
                                file_kind=file_kind,
                            )
                        checkpoint_matched = True
                        continue
                    yield CheckpointedBatchResultRecord(
                        batch_id=validated_batch_id,
                        file_kind=file_kind,
                        record=physical_line.record,
                        checkpoint=current_checkpoint,
                    )

        if not checkpoint_matched:
            raise GatewayError(
                "Provider result checkpoint was not found in current stream",
                response_data={
                    "checkpoint_status": "not_found",
                    "file_kind": checkpoint.file_kind,
                    "record_count": checkpoint.record_count,
                },
            )

    def _validate_resume_checkpoint(
        self,
        resume_after: Optional[BatchResultCheckpoint],
        *,
        batch_id: str,
        endpoint_alias: str,
    ) -> Optional[BatchResultCheckpoint]:
        """Validate a trusted local resume checkpoint before external effects."""
        if resume_after is None:
            return None
        if not isinstance(resume_after, BatchResultCheckpoint):
            raise ValidationError(
                field="resume_after",
                value=type(resume_after).__name__,
                reason="must be a BatchResultCheckpoint instance",
            )
        if resume_after.batch_id != batch_id:
            raise ValidationError(
                field="resume_after.batch_id",
                value=resume_after.batch_id,
                reason="must match the requested batch_id",
            )
        if resume_after.endpoint_alias != endpoint_alias:
            raise ValidationError(
                field="resume_after.endpoint_alias",
                value=resume_after.endpoint_alias,
                reason="must match the requested endpoint_alias",
            )
        return resume_after

    async def _validated_stream_files(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> tuple[str, tuple[tuple[str, Any], tuple[str, Any]]]:
        """Return one terminal batch identity and ordered provider file list."""
        validated_batch_id = _validate_resource_id(batch_id, "batch_id")
        status = await self.get_batch_status(validated_batch_id, endpoint_alias)
        batch_status = str(status.get("status") or "")
        if not status.get("is_complete"):
            raise GatewayError(
                "Batch is not complete",
                response_data={
                    "batch_id": validated_batch_id,
                    "batch_status": batch_status,
                },
            )

        files = (
            ("result", status.get("output_file_id")),
            ("error", status.get("error_file_id")),
        )
        if not any(file_id for _, file_id in files):
            raise GatewayError(
                "Batch exposes no output or error file",
                response_data={"batch_id": validated_batch_id},
            )
        return validated_batch_id, files

    def _enforce_record_limit(self, *, record_count: int, file_kind: str) -> None:
        """Fail before yielding one record above the batch-wide record ceiling."""
        if record_count > self.max_jsonl_records:
            raise GatewayError(
                "Provider JSONL record limit exceeded",
                response_data={
                    "file_kind": file_kind,
                    "limit_records": self.max_jsonl_records,
                    "record_count": record_count,
                },
            )

    def _checkpoint_mismatch_error(
        self,
        checkpoint: BatchResultCheckpoint,
        *,
        file_kind: str,
    ) -> GatewayError:
        """Build one body-free error for a changed resume prefix."""
        return GatewayError(
            "Provider result checkpoint does not match current stream",
            response_data={
                "checkpoint_status": "mismatch",
                "file_kind": file_kind,
                "record_count": checkpoint.record_count,
            },
        )

    async def _iter_jsonl_file(
        self,
        file_id: Any,
        endpoint_alias: str,
        *,
        file_kind: str,
        physical_line_budget: _PhysicalLineBudget,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield JSON objects from one bounded provider file byte stream."""
        async with aclosing(
            self._iter_jsonl_file_lines(
                file_id,
                endpoint_alias,
                file_kind=file_kind,
                physical_line_budget=physical_line_budget,
            )
        ) as physical_lines:
            async for physical_line in physical_lines:
                if physical_line.record is not None:
                    yield physical_line.record

    async def _iter_jsonl_file_lines(
        self,
        file_id: Any,
        endpoint_alias: str,
        *,
        file_kind: str,
        physical_line_budget: _PhysicalLineBudget,
    ) -> AsyncIterator[_PhysicalJsonlLine]:
        """Yield bounded physical lines with optional decoded JSON objects."""
        validated_file_id = _validate_resource_id(file_id, f"{file_kind}_file_id")
        creds = self._credentials(endpoint_alias)
        operation = f"{file_kind.capitalize()} file download"
        async with self._request(
            "get",
            f"{creds.url}/files/{validated_file_id}/content",
            operation=operation,
            headers=self._headers(creds.api_key),
        ) as response:
            if response.status != 200:
                raise GatewayError(
                    f"{operation} failed: {response.status}",
                    status_code=response.status,
                    response_data={"file_kind": file_kind},
                )

            declared_value = getattr(response, "content_length", None)
            declared_bytes: Optional[int] = (
                declared_value
                if isinstance(declared_value, int)
                and not isinstance(declared_value, bool)
                and declared_value >= 0
                else None
            )
            if (
                declared_bytes is not None
                and declared_bytes > self.max_download_bytes
            ):
                raise self._download_limit_error(
                    response,
                    operation,
                    max_bytes=self.max_download_bytes,
                    declared_bytes=declared_bytes,
                    bytes_read=0,
                )

            stream = getattr(response, "content", None)
            iterator = getattr(stream, "iter_chunked", None)
            if not callable(iterator):
                raise GatewayError(
                    f"{operation} response does not expose a bounded byte stream",
                    status_code=response.status,
                    response_data={"error_type": "MissingBoundedStream"},
                )

            pending = bytearray()
            bytes_read = 0
            line_number = 0
            async for chunk in iterator(DOWNLOAD_CHUNK_BYTES):
                if isinstance(chunk, memoryview):
                    chunk_bytes = chunk.nbytes
                elif isinstance(chunk, (bytes, bytearray)):
                    chunk_bytes = len(chunk)
                else:
                    raise GatewayError(
                        f"{operation} response yielded a non-byte stream chunk",
                        status_code=response.status,
                        response_data={"error_type": "InvalidByteChunk"},
                    )
                if chunk_bytes == 0:
                    raise GatewayError(
                        f"{operation} response yielded an empty stream chunk",
                        status_code=response.status,
                        response_data={"error_type": "NoForwardProgress"},
                    )
                if chunk_bytes > DOWNLOAD_CHUNK_BYTES:
                    raise GatewayError(
                        f"{operation} response chunk exceeded byte limit",
                        status_code=response.status,
                        response_data={
                            "error_type": "OversizedByteChunk",
                            "limit_bytes": DOWNLOAD_CHUNK_BYTES,
                            "chunk_bytes": chunk_bytes,
                        },
                    )
                if bytes_read + chunk_bytes > self.max_download_bytes:
                    raise self._download_limit_error(
                        response,
                        operation,
                        max_bytes=self.max_download_bytes,
                        declared_bytes=declared_bytes,
                        bytes_read=bytes_read,
                    )
                normalized_chunk = (
                    chunk.tobytes() if isinstance(chunk, memoryview) else chunk
                )
                bytes_read += chunk_bytes
                pending.extend(normalized_chunk)

                while True:
                    newline_index = pending.find(b"\n")
                    if newline_index < 0:
                        break
                    line = bytes(pending[:newline_index])
                    del pending[: newline_index + 1]
                    line_number += 1
                    physical_line_budget.observe(
                        file_kind=file_kind,
                        file_line_number=line_number,
                    )
                    yield _PhysicalJsonlLine(
                        file_line_number=line_number,
                        raw_line=line,
                        newline_terminated=True,
                        record=self._parse_jsonl_line(
                            line,
                            file_kind=file_kind,
                            line_number=line_number,
                        ),
                    )

                if len(pending) > self.max_jsonl_line_bytes:
                    raise self._line_limit_error(
                        file_kind=file_kind,
                        line_number=line_number + 1,
                        bytes_buffered=len(pending),
                    )

            if pending:
                line_number += 1
                physical_line_budget.observe(
                    file_kind=file_kind,
                    file_line_number=line_number,
                )
                final_line = bytes(pending)
                yield _PhysicalJsonlLine(
                    file_line_number=line_number,
                    raw_line=final_line,
                    newline_terminated=False,
                    record=self._parse_jsonl_line(
                        final_line,
                        file_kind=file_kind,
                        line_number=line_number,
                    ),
                )

    def _line_limit_error(
        self,
        *,
        file_kind: str,
        line_number: int,
        bytes_buffered: int,
    ) -> GatewayError:
        """Build one body-free error for an oversized JSONL line."""
        return GatewayError(
            "Provider JSONL line exceeded byte limit",
            response_data={
                "file_kind": file_kind,
                "line_number": line_number,
                "limit_bytes": self.max_jsonl_line_bytes,
                "bytes_buffered": bytes_buffered,
            },
        )

    def _parse_jsonl_line(
        self,
        line: bytes,
        *,
        file_kind: str,
        line_number: int,
    ) -> Optional[Dict[str, Any]]:
        """Decode and validate one independently bounded JSONL line."""
        if len(line) > self.max_jsonl_line_bytes:
            raise self._line_limit_error(
                file_kind=file_kind,
                line_number=line_number,
                bytes_buffered=len(line),
            )
        if line.endswith(b"\r"):
            line = line[:-1]
        if not line:
            return None

        decode_error: Optional[GatewayError] = None
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            decode_error = GatewayError(
                f"{file_kind.capitalize()} file returned invalid UTF-8",
                response_data={
                    "file_kind": file_kind,
                    "line_number": line_number,
                    "error_type": type(exc).__name__,
                    "byte_offset": exc.start,
                },
            )
        if decode_error is not None:
            raise decode_error

        parse_error: Optional[GatewayError] = None
        try:
            parsed = json.loads(
                text,
                parse_constant=_reject_non_finite_json_constant,
                object_pairs_hook=_object_without_duplicate_names,
            )
        except (ValueError, RecursionError):
            parse_error = GatewayError(
                f"Malformed {file_kind} line {line_number}",
                response_data={
                    "file_kind": file_kind,
                    "line_number": line_number,
                },
            )
        if parse_error is not None:
            raise parse_error

        if not isinstance(parsed, dict):
            raise GatewayError(
                f"Non-object {file_kind} line {line_number}",
                response_data={
                    "file_kind": file_kind,
                    "line_number": line_number,
                    "response_type": type(parsed).__name__,
                },
            )
        return parsed
