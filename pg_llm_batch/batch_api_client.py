# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""OpenAI-compatible Batch API client (memory-only JSONL).

Talks to any OpenAI-compatible ``/files`` + ``/batches`` endpoint (OpenAI,
Azure OpenAI, a LiteLLM gateway, ...). Credentials are resolved through a
pluggable ``credentials`` seam (default: the Postgres KV/secret store) — never
from ``os.getenv``. JSONL payloads are streamed from Postgres, never disk.

Extracted and relicensed (Apache-2.0) from xtrmLLMBatchPython.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from math import isfinite
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .db import load_virtual_payload
from .exceptions import GatewayError, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "pg-llm-batch"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_CONTROL_RESPONSE_BYTES = 1 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
DEFAULT_MAX_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5
DEFAULT_RETRY_MAX_DELAY_SECONDS = 30.0
RETRYABLE_GET_STATUSES = frozenset({408, 425, 429, 502, 503, 504})
TERMINAL_BATCH_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})
LOOPBACK_HOSTNAMES = frozenset({"localhost"})
REMOTE_RESOURCE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
BATCH_ENDPOINT_PATTERN = re.compile(
    r"/[A-Za-z0-9_~-]+(?:/[A-Za-z0-9._~-]+){0,15}\Z"
)


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC time for retry calculations."""
    return datetime.now(timezone.utc)


def _parse_retry_after(value: Any, now: datetime) -> Optional[float]:
    """Parse an RFC Retry-After delta or HTTP-date into a non-negative delay."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.isascii() and candidate.isdigit():
        return float(candidate)
    try:
        parsed = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delay = (
        parsed.astimezone(timezone.utc) - now.astimezone(timezone.utc)
    ).total_seconds()
    return max(0.0, delay)


def _normalize_retry_delay(field: str, value: Any) -> float:
    """Validate and normalize one non-negative finite retry delay."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
        or float(value) < 0
    ):
        raise ValidationError(
            field=field,
            value=value,
            reason="must be a finite non-negative number of seconds",
        )
    return float(value)


def _bounded_transport_error_type(error: BaseException) -> str:
    """Return one finite transport category without dependency-defined class names."""
    if isinstance(error, aiohttp.ServerFingerprintMismatch):
        return "ServerFingerprintMismatch"
    if isinstance(error, aiohttp.ClientConnectorCertificateError):
        return "ClientConnectorCertificateError"
    if isinstance(error, aiohttp.ClientSSLError):
        return "ClientSSLError"
    if isinstance(error, asyncio.TimeoutError):
        return "TimeoutError"
    return "ClientError"


@dataclass
class GatewayCredentials:
    """Resolved endpoint credentials for a single batch backend."""

    url: str
    api_key: str


# A credentials provider returns GatewayCredentials for a given endpoint alias.
CredentialsProvider = Callable[[str], GatewayCredentials]


def _validate_resource_id(value: Any, field: str) -> str:
    """Validate one provider resource identifier used in a URL path segment."""
    if not isinstance(value, str) or REMOTE_RESOURCE_ID_PATTERN.fullmatch(value) is None:
        raise ValidationError(
            field=field,
            value=value,
            reason=(
                "must be 1-256 ASCII characters beginning with an alphanumeric "
                "character and containing only letters, digits, dot, underscore, "
                "colon, or hyphen"
            ),
        )
    return value


def _validate_batch_endpoint(value: Any) -> str:
    """Validate the relative provider endpoint submitted with a batch job."""
    if (
        not isinstance(value, str)
        or len(value) > 256
        or BATCH_ENDPOINT_PATTERN.fullmatch(value) is None
        or any(segment in {".", ".."} for segment in value.split("/")[1:])
    ):
        raise ValidationError(
            field="endpoint",
            value=value,
            reason=(
                "must be an absolute 1-256 character API path with 1-16 "
                "non-empty ASCII segments using only letters, digits, dot, "
                "underscore, tilde, or hyphen; traversal, queries, fragments, "
                "percent escapes, and trailing slashes are not allowed"
            ),
        )
    return value


def _is_loopback_host(hostname: str) -> bool:
    """Return whether a hostname is an explicit local-loopback destination."""
    if hostname.lower() in LOOPBACK_HOSTNAMES:
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _normalize_gateway_url(value: Any) -> str:
    """Validate and normalize a credential-bearing gateway base URL."""
    raw = str(value).strip()
    if (
        not raw
        or "\\" in raw
        or any(character.isspace() or ord(character) < 32 for character in raw)
    ):
        raise GatewayError(
            "Gateway base_url must be a valid URL without whitespace, controls, "
            "or backslashes"
        )

    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise GatewayError("Gateway base_url contains an invalid host or port") from exc

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname:
        raise GatewayError("Gateway base_url must use http or https with a hostname")
    if port == 0:
        raise GatewayError("Gateway base_url port must be between 1 and 65535")
    if parsed.username is not None or parsed.password is not None:
        raise GatewayError("Gateway base_url must not contain user information")
    if parsed.query or parsed.fragment:
        raise GatewayError("Gateway base_url must not contain a query or fragment")
    if scheme == "http" and not _is_loopback_host(hostname):
        raise GatewayError(
            "Gateway base_url must use HTTPS except for explicit loopback endpoints"
        )

    return urlunsplit((scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def config_credentials_provider(
    config_store: Any, secret_store: Any
) -> CredentialsProvider:
    """Build a credentials provider backed by the KV config + secret stores.

    Base URLs live in ``com_config`` under category ``gateway`` keyed by alias;
    API keys live encrypted in ``com_secrets`` under ``gateway_api_key.<alias>``.
    """

    def _provider(endpoint_alias: str) -> GatewayCredentials:
        """Resolve the base URL and API key for one endpoint alias from the stores."""
        url = config_store.get("gateway", endpoint_alias, None)
        if not url:
            url = config_store.get("gateway", "base_url", None)
        if not url:
            raise GatewayError(
                f"No gateway base_url configured for alias '{endpoint_alias}'"
            )
        normalized_url = _normalize_gateway_url(url)
        api_key = secret_store.require_secret(f"gateway_api_key.{endpoint_alias}")
        return GatewayCredentials(url=normalized_url, api_key=api_key)

    return _provider


class BatchAPIClient:
    """Async client for submit / poll / retrieve against a Batch API."""

    def __init__(
        self,
        postgres_dsn: str,
        credentials: CredentialsProvider,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        max_control_response_bytes: int = DEFAULT_MAX_CONTROL_RESPONSE_BYTES,
        max_retry_attempts: int = DEFAULT_MAX_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = DEFAULT_RETRY_MAX_DELAY_SECONDS,
    ) -> None:
        """Initialize the client with bounded HTTP, download, and retry resources."""
        if not postgres_dsn:
            raise RuntimeError("A Postgres DSN is required (memory-only JSONL)")
        try:
            normalized_timeout = float(request_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                field="request_timeout_seconds",
                value=request_timeout_seconds,
                reason="must be a finite number greater than zero",
            ) from exc
        if (
            isinstance(request_timeout_seconds, bool)
            or not isfinite(normalized_timeout)
            or normalized_timeout <= 0
        ):
            raise ValidationError(
                field="request_timeout_seconds",
                value=request_timeout_seconds,
                reason="must be a finite number greater than zero",
            )
        if (
            isinstance(max_download_bytes, bool)
            or not isinstance(max_download_bytes, int)
            or max_download_bytes <= 0
        ):
            raise ValidationError(
                field="max_download_bytes",
                value=max_download_bytes,
                reason="must be a positive integer number of bytes",
            )
        if (
            isinstance(max_retry_attempts, bool)
            or not isinstance(max_retry_attempts, int)
            or max_retry_attempts <= 0
        ):
            raise ValidationError(
                field="max_retry_attempts",
                value=max_retry_attempts,
                reason="must be a positive integer total-attempt limit",
            )
        if (
            isinstance(max_control_response_bytes, bool)
            or not isinstance(max_control_response_bytes, int)
            or max_control_response_bytes <= 0
        ):
            raise ValidationError(
                field="max_control_response_bytes",
                value=max_control_response_bytes,
                reason="must be a positive integer number of bytes",
            )
        normalized_retry_base = _normalize_retry_delay(
            "retry_base_delay_seconds", retry_base_delay_seconds
        )
        normalized_retry_max = _normalize_retry_delay(
            "retry_max_delay_seconds", retry_max_delay_seconds
        )
        if normalized_retry_base > normalized_retry_max:
            raise ValidationError(
                field="retry_base_delay_seconds",
                value=retry_base_delay_seconds,
                reason="must not exceed retry_max_delay_seconds",
            )
        self.postgres_dsn = postgres_dsn
        self._credentials = credentials
        self.request_timeout_seconds = normalized_timeout
        self.max_download_bytes = max_download_bytes
        self.max_control_response_bytes = max_control_response_bytes
        self.max_retry_attempts = max_retry_attempts
        self.retry_base_delay_seconds = normalized_retry_base
        self.retry_max_delay_seconds = normalized_retry_max
        self._request_timeout = aiohttp.ClientTimeout(total=normalized_timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "BatchAPIClient":
        """Open and return the asynchronous HTTP client context."""
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the HTTP session when leaving the asynchronous context."""
        if self._session:
            await self._session.close()
            self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Return the current HTTP session, creating one on first use."""
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    def _fallback_retry_delay(self, failed_attempt: int) -> float:
        """Return bounded equal-jitter exponential delay after one failed attempt."""
        ceiling = min(
            self.retry_base_delay_seconds * (2 ** (failed_attempt - 1)),
            self.retry_max_delay_seconds,
        )
        if ceiling <= 0:
            return 0.0
        return random.uniform(ceiling / 2, ceiling)

    def _retry_delay_for_response(
        self,
        response: Any,
        failed_attempt: int,
    ) -> Optional[float]:
        """Choose a bounded response retry delay or refuse excessive guidance."""
        headers = getattr(response, "headers", None)
        header_get = getattr(headers, "get", None)
        retry_after_value = (
            header_get("Retry-After") if callable(header_get) else None
        )
        retry_after = _parse_retry_after(retry_after_value, _utc_now())
        if retry_after is not None:
            if retry_after > self.retry_max_delay_seconds:
                return None
            return retry_after
        return self._fallback_retry_delay(failed_attempt)

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Yield a response, retrying bounded GET acquisition failures only."""
        session = self._get_session()
        normalized_method = method.lower()
        request = getattr(session, normalized_method)
        retry_safe = normalized_method == "get"
        attempt = 1
        while True:
            delay: Optional[float] = None
            retry_reason = ""
            terminal_error_type: Optional[str] = None
            response_handed_off = False
            try:
                async with request(
                    url,
                    timeout=self._request_timeout,
                    allow_redirects=False,
                    **kwargs,
                ) as response:
                    if (
                        retry_safe
                        and attempt < self.max_retry_attempts
                        and response.status in RETRYABLE_GET_STATUSES
                    ):
                        delay = self._retry_delay_for_response(response, attempt)
                        if delay is None:
                            response_handed_off = True
                            yield response
                            return
                        retry_reason = f"HTTP {response.status}"
                    else:
                        response_handed_off = True
                        yield response
                        return
            except GatewayError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if response_handed_off:
                    raise
                bounded_error_type = _bounded_transport_error_type(exc)
                if (
                    not retry_safe
                    or attempt >= self.max_retry_attempts
                    or isinstance(
                        exc,
                        (aiohttp.ClientSSLError, aiohttp.ServerFingerprintMismatch),
                    )
                ):
                    terminal_error_type = bounded_error_type
                else:
                    delay = self._fallback_retry_delay(attempt)
                    retry_reason = bounded_error_type

            if terminal_error_type is not None:
                raise GatewayError(
                    f"{operation} transport failed",
                    response_data={
                        "error_type": terminal_error_type,
                        "timeout_seconds": self.request_timeout_seconds,
                    },
                )

            logger.warning(
                "%s retrying idempotent GET after %s "
                "(attempt %s/%s, delay %.3fs)",
                operation,
                retry_reason,
                attempt,
                self.max_retry_attempts,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1

    async def _read_json_object(
        self,
        response: Any,
        operation: str,
    ) -> Dict[str, Any]:
        """Decode one bounded control-plane body and require a JSON object."""
        content = await self._read_bounded_utf8(
            response,
            operation,
            max_bytes=self.max_control_response_bytes,
        )
        try:
            result = json.loads(content)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise GatewayError(
                f"{operation} returned invalid JSON",
                status_code=getattr(response, "status", None),
                response_data={"error_type": type(exc).__name__},
            ) from exc
        if not isinstance(result, dict):
            raise GatewayError(
                f"{operation} returned a non-object JSON response",
                status_code=getattr(response, "status", None),
                response_data={"response_type": type(result).__name__},
            )
        return result

    def _download_limit_error(
        self,
        response: Any,
        operation: str,
        *,
        max_bytes: int,
        declared_bytes: Optional[int],
        bytes_read: int,
    ) -> GatewayError:
        """Build a body-free error for one explicit response byte limit."""
        return GatewayError(
            f"{operation} exceeded download limit",
            status_code=getattr(response, "status", None),
            response_data={
                "limit_bytes": max_bytes,
                "declared_bytes": declared_bytes,
                "bytes_read": bytes_read,
            },
        )

    async def _read_bounded_utf8(
        self,
        response: Any,
        operation: str,
        *,
        max_bytes: int,
    ) -> str:
        """Read one strict UTF-8 response body within an explicit byte limit."""
        declared_value = getattr(response, "content_length", None)
        declared_bytes = (
            declared_value
            if isinstance(declared_value, int)
            and not isinstance(declared_value, bool)
            and declared_value >= 0
            else None
        )
        if declared_bytes is not None and declared_bytes > max_bytes:
            raise self._download_limit_error(
                response,
                operation,
                max_bytes=max_bytes,
                declared_bytes=declared_bytes,
                bytes_read=0,
            )
        stream = getattr(response, "content", None)
        iterator = getattr(stream, "iter_chunked", None)
        if not callable(iterator):
            raise GatewayError(
                f"{operation} response does not expose a bounded byte stream",
                status_code=getattr(response, "status", None),
                response_data={"error_type": "MissingBoundedStream"},
            )
        payload = bytearray()
        async for chunk in iterator(DOWNLOAD_CHUNK_BYTES):
            if isinstance(chunk, memoryview):
                chunk_bytes = chunk.nbytes
            elif isinstance(chunk, (bytes, bytearray)):
                chunk_bytes = len(chunk)
            else:
                raise GatewayError(
                    f"{operation} response yielded a non-byte stream chunk",
                    status_code=getattr(response, "status", None),
                    response_data={"error_type": "InvalidByteChunk"},
                )
            if len(payload) + chunk_bytes > max_bytes:
                raise self._download_limit_error(
                    response,
                    operation,
                    max_bytes=max_bytes,
                    declared_bytes=declared_bytes,
                    bytes_read=len(payload),
                )
            if isinstance(chunk, memoryview):
                payload.extend(chunk.tobytes())
            else:
                payload.extend(chunk)
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GatewayError(
                f"{operation} returned invalid UTF-8",
                status_code=getattr(response, "status", None),
                response_data={
                    "error_type": type(exc).__name__,
                    "byte_offset": exc.start,
                },
            ) from exc

    def _headers(self, api_key: str, *, json_body: bool = False) -> Dict[str, str]:
        """Build request headers with bearer auth, optionally declaring a JSON body."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _resolve_memory_identifier(self, file_path: str) -> str:
        """Extract and validate the file id from a ``memory://`` payload reference."""
        if file_path.startswith("memory://"):
            file_id = file_path.split("memory://", 1)[1]
            if file_id:
                return _validate_resource_id(file_id, "file_id")
        raise RuntimeError(
            "JSONL payloads must be memory:// references (PostgreSQL-backed)."
        )

    async def _load_payload_bytes(self, file_id: str) -> bytes:
        """Load a Postgres-backed virtual JSONL payload and return it as UTF-8 bytes."""
        payload = await asyncio.to_thread(
            load_virtual_payload, self.postgres_dsn, file_id
        )
        if not payload:
            raise FileNotFoundError(
                f"Virtual batch payload not found for file_id={file_id}"
            )
        return payload.encode("utf-8")

    async def upload_jsonl(
        self,
        file_path: str,
        endpoint_alias: str,
        purpose: str = "batch",
    ) -> Dict[str, Any]:
        """Upload a memory-backed JSONL payload to the Files API."""
        file_id = self._resolve_memory_identifier(file_path)
        creds = self._credentials(endpoint_alias)
        payload_bytes = await self._load_payload_bytes(file_id)

        data = aiohttp.FormData()
        data.add_field("purpose", purpose)
        data.add_field(
            "file",
            payload_bytes,
            filename=f"{file_id}.jsonl",
            content_type="application/jsonl",
        )
        async with self._request(
            "post",
            f"{creds.url}/files",
            operation="Files API upload",
            data=data,
            headers=self._headers(creds.api_key),
        ) as response:
            if response.status != 200:
                raise GatewayError(
                    f"Files API upload failed: {response.status}",
                    status_code=response.status,
                    response_data={"error_type": "ProviderHTTPError"},
                )
            result = await self._read_json_object(response, "Files API upload")
            logger.info("Uploaded JSONL file: %s", result.get("id"))
            return result

    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a batch job from an uploaded input file id."""
        validated_file_id = _validate_resource_id(input_file_id, "input_file_id")
        validated_endpoint = _validate_batch_endpoint(endpoint)
        creds = self._credentials(endpoint_alias)
        payload: Dict[str, Any] = {
            "input_file_id": validated_file_id,
            "endpoint": validated_endpoint,
            "completion_window": "24h",
        }
        if metadata:
            payload["metadata"] = metadata
        async with self._request(
            "post",
            f"{creds.url}/batches",
            operation="Batch creation",
            json=payload,
            headers=self._headers(creds.api_key, json_body=True),
        ) as response:
            if response.status not in (200, 201, 202):
                raise GatewayError(
                    f"Batch creation failed: {response.status}",
                    status_code=response.status,
                    response_data={"error_type": "ProviderHTTPError"},
                )
            result = await self._read_json_object(response, "Batch creation")
            logger.info("Created batch job: %s", result.get("id"))
            return result

    async def get_batch_status(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Poll a batch job and annotate progress/completion."""
        validated_batch_id = _validate_resource_id(batch_id, "batch_id")
        creds = self._credentials(endpoint_alias)
        async with self._request(
            "get",
            f"{creds.url}/batches/{validated_batch_id}",
            operation="Batch status",
            headers=self._headers(creds.api_key),
        ) as response:
            if response.status != 200:
                raise GatewayError(
                    f"Batch status failed: {response.status}",
                    status_code=response.status,
                    response_data={"error_type": "ProviderHTTPError"},
                )
            result = await self._read_json_object(response, "Batch status")
            counts = result.get("request_counts") or {}
            total = counts.get("total", 0)
            done = counts.get("completed", 0) + counts.get("failed", 0)
            result["progress_percentage"] = (
                round((done / total) * 100, 2) if total else 0
            )
            result["is_complete"] = result.get("status") in TERMINAL_BATCH_STATUSES
            return result

    async def wait_for_batch(
        self,
        batch_id: str,
        endpoint_alias: str,
        *,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 3600.0,
    ) -> Dict[str, Any]:
        """Wait until a batch reaches a terminal state or the timeout expires."""
        if poll_interval_seconds <= 0:
            raise ValidationError(
                field="poll_interval_seconds",
                value=poll_interval_seconds,
                reason="must be greater than zero",
            )
        if timeout_seconds <= 0:
            raise ValidationError(
                field="timeout_seconds",
                value=timeout_seconds,
                reason="must be greater than zero",
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while True:
            status = await self.get_batch_status(batch_id, endpoint_alias)
            if status.get("is_complete"):
                return status

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise GatewayError(
                    f"Timed out waiting for batch {batch_id}",
                    response_data={
                        "batch_id": batch_id,
                        "last_status": status.get("status"),
                        "timeout_seconds": timeout_seconds,
                    },
                )
            await asyncio.sleep(min(poll_interval_seconds, remaining))

    @staticmethod
    def _parse_jsonl_content(
        content: str,
        *,
        batch_id: str,
        file_kind: str,
    ) -> List[Dict[str, Any]]:
        """Parse JSONL text into a list of objects, rejecting malformed or non-object lines."""
        parsed_lines: List[Dict[str, Any]] = []
        for line_number, line in enumerate(content.strip().split("\n"), start=1):
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
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
            parsed_lines.append(parsed)
        return parsed_lines

    async def _download_jsonl_file(
        self,
        file_id: Any,
        endpoint_alias: str,
        *,
        batch_id: str,
        file_kind: str,
    ) -> List[Dict[str, Any]]:
        """Download a batch output/error file by id and parse it into JSONL records."""
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
                    response_data={"error_type": "ProviderHTTPError"},
                )
            content = await self._read_bounded_utf8(
                response,
                operation,
                max_bytes=self.max_download_bytes,
            )
        return self._parse_jsonl_content(
            content,
            batch_id=batch_id,
            file_kind=file_kind,
        )

    async def download_results(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Download output and provider error files into bounded memory."""
        status = await self.get_batch_status(batch_id, endpoint_alias)
        if not status.get("is_complete"):
            return {
                "success": False,
                "reason": f"Batch not complete: {status.get('status')}",
            }

        output_file_id = status.get("output_file_id")
        error_file_id = status.get("error_file_id")
        if not output_file_id and not error_file_id:
            return {"success": False, "reason": "No output_file_id on batch"}

        responses = (
            await self._download_jsonl_file(
                output_file_id,
                endpoint_alias,
                batch_id=batch_id,
                file_kind="result",
            )
            if output_file_id
            else []
        )
        errors = (
            await self._download_jsonl_file(
                error_file_id,
                endpoint_alias,
                batch_id=batch_id,
                file_kind="error",
            )
            if error_file_id
            else []
        )
        batch_status = str(status.get("status") or "")
        return {
            "success": True,
            "batch_succeeded": batch_status == "completed",
            "batch_id": batch_id,
            "batch_status": batch_status,
            "output_file_id": output_file_id,
            "error_file_id": error_file_id,
            "response_count": len(responses),
            "error_count": len(errors),
            "has_errors": bool(errors),
            "responses": responses,
            "errors": errors,
        }

    async def cancel_batch(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Cancel an in-flight batch job."""
        validated_batch_id = _validate_resource_id(batch_id, "batch_id")
        creds = self._credentials(endpoint_alias)
        async with self._request(
            "post",
            f"{creds.url}/batches/{validated_batch_id}/cancel",
            operation="Batch cancellation",
            headers=self._headers(creds.api_key),
        ) as response:
            if response.status not in (200, 202):
                return {
                    "success": False,
                    "reason": "Batch cancellation rejected by provider",
                    "status_code": response.status,
                }
            result = await self._read_json_object(response, "Batch cancellation")
            return {
                "success": True,
                "batch_id": validated_batch_id,
                "status": result.get("status", "cancelling"),
            }
