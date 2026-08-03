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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import ip_address
from math import isfinite
from typing import Any, AsyncIterator, Callable, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .db import load_virtual_payload
from .exceptions import GatewayError, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "pg-llm-batch"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
TERMINAL_BATCH_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})
LOOPBACK_HOSTNAMES = frozenset({"localhost"})


@dataclass
class GatewayCredentials:
    """Resolved endpoint credentials for a single batch backend."""

    url: str
    api_key: str


# A credentials provider returns GatewayCredentials for a given endpoint alias.
CredentialsProvider = Callable[[str], GatewayCredentials]


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
        url = config_store.get("gateway", endpoint_alias, None)
        if not url:
            # fall back to a single default gateway url
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
    ) -> None:
        """Initialize the client with a payload store and bounded HTTP timeout."""
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
        self.postgres_dsn = postgres_dsn
        self._credentials = credentials
        self.request_timeout_seconds = normalized_timeout
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
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        session = self._get_session()
        request = getattr(session, method.lower())
        try:
            async with request(
                url,
                timeout=self._request_timeout,
                allow_redirects=False,
                **kwargs,
            ) as response:
                yield response
        except GatewayError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise GatewayError(
                f"{operation} transport failed",
                response_data={
                    "error_type": type(exc).__name__,
                    "timeout_seconds": self.request_timeout_seconds,
                },
            ) from exc

    async def _read_json_object(self, response: Any, operation: str) -> Dict[str, Any]:
        try:
            result = await response.json()
        except (aiohttp.ClientError, ValueError, UnicodeError) as exc:
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

    def _headers(self, api_key: str, *, json_body: bool = False) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    def _resolve_memory_identifier(self, file_path: str) -> str:
        if file_path.startswith("memory://"):
            file_id = file_path.split("memory://", 1)[1]
            if file_id:
                return file_id
        raise RuntimeError(
            "JSONL payloads must be memory:// references (PostgreSQL-backed)."
        )

    async def _load_payload_bytes(self, file_id: str) -> bytes:
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
        creds = self._credentials(endpoint_alias)
        file_id = self._resolve_memory_identifier(file_path)
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
            result = await self._read_json_object(response, "Files API upload")
            if response.status != 200:
                raise GatewayError(
                    f"Files API upload failed: {response.status}",
                    status_code=response.status,
                    response_data=result,
                )
            logger.info("Uploaded JSONL file: %s", result.get("id"))
            return result

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------
    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a batch job from an uploaded input file id."""
        creds = self._credentials(endpoint_alias)
        payload: Dict[str, Any] = {
            "input_file_id": input_file_id,
            "endpoint": endpoint,
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
            result = await self._read_json_object(response, "Batch creation")
            if response.status not in (200, 201, 202):
                raise GatewayError(
                    f"Batch creation failed: {response.status}",
                    status_code=response.status,
                    response_data=result,
                )
            logger.info("Created batch job: %s", result.get("id"))
            return result

    async def get_batch_status(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Poll a batch job and annotate progress/completion."""
        creds = self._credentials(endpoint_alias)
        async with self._request(
            "get",
            f"{creds.url}/batches/{batch_id}",
            operation="Batch status",
            headers=self._headers(creds.api_key),
        ) as response:
            result = await self._read_json_object(response, "Batch status")
            if response.status != 200:
                raise GatewayError(
                    f"Batch status failed: {response.status}",
                    status_code=response.status,
                    response_data=result,
                )
            # A gateway returns request_counts as null (present, but None) while
            # a batch is still validating; `or {}` treats null like absent so the
            # progress math below never dereferences None.
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

    async def download_results(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Download and parse batch results into memory (no disk writes)."""
        status = await self.get_batch_status(batch_id, endpoint_alias)
        if not status.get("is_complete"):
            return {
                "success": False,
                "reason": f"Batch not complete: {status.get('status')}",
            }
        output_file_id = status.get("output_file_id")
        if not output_file_id:
            return {"success": False, "reason": "No output_file_id on batch"}

        creds = self._credentials(endpoint_alias)
        async with self._request(
            "get",
            f"{creds.url}/files/{output_file_id}/content",
            operation="Result download",
            headers=self._headers(creds.api_key),
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise GatewayError(
                    f"Result download failed: {response.status}",
                    status_code=response.status,
                    response_data={"body": error_text},
                )
            content = await response.text()

        responses = []
        for line_number, line in enumerate(content.strip().split("\n"), start=1):
            if not line:
                continue
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise GatewayError(
                    f"Malformed result line {line_number} for batch {batch_id}",
                    response_data={"line_number": line_number},
                ) from exc
        return {
            "success": True,
            "batch_id": batch_id,
            "output_file_id": output_file_id,
            "response_count": len(responses),
            "responses": responses,
        }

    async def cancel_batch(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Cancel an in-flight batch job."""
        creds = self._credentials(endpoint_alias)
        async with self._request(
            "post",
            f"{creds.url}/batches/{batch_id}/cancel",
            operation="Batch cancellation",
            headers=self._headers(creds.api_key),
        ) as response:
            result = await self._read_json_object(response, "Batch cancellation")
            if response.status not in (200, 202):
                error = result.get("error")
                reason = (
                    error.get("message", "Unknown error")
                    if isinstance(error, dict)
                    else "Unknown error"
                )
                return {"success": False, "reason": reason}
            return {
                "success": True,
                "batch_id": batch_id,
                "status": result.get("status", "cancelling"),
            }
