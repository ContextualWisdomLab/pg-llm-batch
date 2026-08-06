# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Bounded incremental retrieval for provider result and error JSONL files."""

from __future__ import annotations

import json
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from .batch_api_client import (
    DOWNLOAD_CHUNK_BYTES,
    BatchAPIClient,
    _validate_resource_id,
)
from .exceptions import GatewayError, ValidationError

DEFAULT_MAX_JSONL_LINE_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_JSONL_RECORDS = 100_000


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


class StreamingBatchAPIClient(BatchAPIClient):
    """Batch client that yields provider JSONL records without whole-body storage.

    This opt-in client preserves :class:`BatchAPIClient` HTTP, credential, retry,
    redirect, and total-download controls. It additionally limits the bytes in
    one unterminated JSONL line and the number of records yielded for one batch.
    """

    def __init__(
        self,
        postgres_dsn: str,
        credentials: Any,
        *,
        max_jsonl_line_bytes: int = DEFAULT_MAX_JSONL_LINE_BYTES,
        max_jsonl_records: int = DEFAULT_MAX_JSONL_RECORDS,
        **kwargs: Any,
    ) -> None:
        """Initialize bounded incremental JSONL retrieval resources."""
        validated_line_bytes = _validate_positive_integer(
            "max_jsonl_line_bytes", max_jsonl_line_bytes
        )
        validated_records = _validate_positive_integer(
            "max_jsonl_records", max_jsonl_records
        )
        super().__init__(postgres_dsn, credentials, **kwargs)
        self.max_jsonl_line_bytes = validated_line_bytes
        self.max_jsonl_records = validated_records

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

    async def iter_batch_records(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> AsyncIterator[BatchResultRecord]:
        """Yield bounded result records followed by bounded provider error records.

        The batch status is retrieved once before file access. Iteration is
        permitted only for a terminal batch that exposes at least one provider
        output or error file identifier. Consumers that may exit early should
        use :meth:`open_batch_records` so the active response closes
        deterministically.
        """
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

        record_count = 0
        for file_kind, file_id in files:
            if not file_id:
                continue
            async with aclosing(
                self._iter_jsonl_file(
                    file_id,
                    endpoint_alias,
                    file_kind=file_kind,
                )
            ) as file_records:
                async for record in file_records:
                    record_count += 1
                    if record_count > self.max_jsonl_records:
                        raise GatewayError(
                            "Provider JSONL record limit exceeded",
                            response_data={
                                "file_kind": file_kind,
                                "limit_records": self.max_jsonl_records,
                                "record_count": record_count,
                            },
                        )
                    yield BatchResultRecord(validated_batch_id, file_kind, record)

    async def _iter_jsonl_file(
        self,
        file_id: Any,
        endpoint_alias: str,
        *,
        file_kind: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield JSON objects from one bounded provider file byte stream."""
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
                    parsed_line = self._parse_jsonl_line(
                        line,
                        file_kind=file_kind,
                        line_number=line_number,
                    )
                    if parsed_line is not None:
                        yield parsed_line

                if len(pending) > self.max_jsonl_line_bytes:
                    raise self._line_limit_error(
                        file_kind=file_kind,
                        line_number=line_number + 1,
                        bytes_buffered=len(pending),
                    )

            if pending:
                line_number += 1
                final_record = self._parse_jsonl_line(
                    bytes(pending),
                    file_kind=file_kind,
                    line_number=line_number,
                )
                if final_record is not None:
                    yield final_record

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
