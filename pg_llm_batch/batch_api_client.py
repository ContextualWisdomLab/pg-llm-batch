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
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import aiohttp

from .db import load_virtual_payload
from .exceptions import GatewayError

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "pg-llm-batch"


@dataclass
class GatewayCredentials:
    """Resolved endpoint credentials for a single batch backend."""

    url: str
    api_key: str


# A credentials provider returns GatewayCredentials for a given endpoint alias.
CredentialsProvider = Callable[[str], GatewayCredentials]


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
        api_key = secret_store.require_secret(f"gateway_api_key.{endpoint_alias}")
        return GatewayCredentials(url=str(url).rstrip("/"), api_key=api_key)

    return _provider


class BatchAPIClient:
    """Async client for submit / poll / retrieve against a Batch API."""

    def __init__(
        self,
        postgres_dsn: str,
        credentials: CredentialsProvider,
    ) -> None:
        """Initialize the client with a PostgreSQL payload store and credentials."""
        if not postgres_dsn:
            raise RuntimeError("A Postgres DSN is required (memory-only JSONL)")
        self.postgres_dsn = postgres_dsn
        self._credentials = credentials
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
        session = self._get_session()
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
        async with session.post(
            f"{creds.url}/files", data=data, headers=self._headers(creds.api_key)
        ) as response:
            result = await response.json()
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
        session = self._get_session()
        payload: Dict[str, Any] = {
            "input_file_id": input_file_id,
            "endpoint": endpoint,
            "completion_window": "24h",
        }
        if metadata:
            payload["metadata"] = metadata
        async with session.post(
            f"{creds.url}/batches",
            json=payload,
            headers=self._headers(creds.api_key, json_body=True),
        ) as response:
            result = await response.json()
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
        session = self._get_session()
        async with session.get(
            f"{creds.url}/batches/{batch_id}",
            headers=self._headers(creds.api_key),
        ) as response:
            result = await response.json()
            if response.status != 200:
                raise GatewayError(
                    f"Batch status failed: {response.status}",
                    status_code=response.status,
                    response_data=result,
                )
            counts = result.get("request_counts", {})
            total = counts.get("total", 0)
            done = counts.get("completed", 0) + counts.get("failed", 0)
            result["progress_percentage"] = (
                round((done / total) * 100, 2) if total else 0
            )
            result["is_complete"] = result.get("status") in (
                "completed",
                "failed",
                "expired",
            )
            return result

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
        session = self._get_session()
        async with session.get(
            f"{creds.url}/files/{output_file_id}/content",
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

        responses = [json.loads(line) for line in content.strip().split("\n") if line]
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
        session = self._get_session()
        async with session.post(
            f"{creds.url}/batches/{batch_id}/cancel",
            headers=self._headers(creds.api_key),
        ) as response:
            result = await response.json()
            if response.status not in (200, 202):
                return {
                    "success": False,
                    "reason": result.get("error", {}).get("message", "Unknown error"),
                }
            return {
                "success": True,
                "batch_id": batch_id,
                "status": result.get("status", "cancelling"),
            }
