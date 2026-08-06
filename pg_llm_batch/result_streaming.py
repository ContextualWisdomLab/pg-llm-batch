# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Bounded incremental retrieval for provider result and error JSONL files."""

from __future__ import annotations

import json
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
        super().__init__(postgres_dsn, credentials, **kwargs)
        self.max_jsonl_line_bytes = _validate_positive_integer(
            "max_jsonl_line_bytes", max_jsonl_line_bytes
        )
        self.max_jsonl_records = _validate_positive_integer(
            "max_jsonl_records", max_jsonl_records
        )

    async def iter_batch_records(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> AsyncIterator[BatchResultRecord]:
        """Yield bounded result records followed by bounded provider error records.

        The batch status is retrieved once before file access. Iteration is
        permitted only for a terminal batch that exposes at least one provider
        output or error file identifier.
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
            async for record in self._iter_jsonl_file(
                file_id,
                endpoint_alias,
                batch_id=validated_batch_id,
                file_kind=file_kind,
            ):
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
        batch_id: str,
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
                    normalized_chunk = chunk.tobytes()
                elif isinstance(chunk, (bytes, bytearray)):
                    chunk_bytes = len(chunk)
                    normalized_chunk = chunk
                else:
                    raise GatewayError(
                        f"{operation} response yielded a non-byte stream chunk",
                        status_code=response.status,
                        response_data={"error_type": "InvalidByteChunk"},
                    )
                if bytes_read + chunk_bytes > self.max_download_bytes:
                    raise self._download_limit_error(
                        response,
                        operation,
                        max_bytes=self.max_download_bytes,
                        declared_bytes=declared_bytes,
                        bytes_read=bytes_read,
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
                        batch_id=batch_id,
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
                    batch_id=batch_id,
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
        batch_id: str,
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
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GatewayError(
                f"{file_kind.capitalize()} file returned invalid UTF-8",
                response_data={
                    "file_kind": file_kind,
                    "line_number": line_number,
                    "error_type": type(exc).__name__,
                    "byte_offset": exc.start,
                },
            ) from exc
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise GatewayError(
                f"Malformed {file_kind} line {line_number} for batch {batch_id}",
                response_data={
                    "file_kind": file_kind,
                    "line_number": line_number,
                },
            ) from exc
        if not isinstance(parsed, dict):
            raise GatewayError(
                f"Non-object {file_kind} line {line_number} for batch {batch_id}",
                response_data={
                    "file_kind": file_kind,
                    "line_number": line_number,
                    "response_type": type(parsed).__name__,
                },
            )
        return parsed
