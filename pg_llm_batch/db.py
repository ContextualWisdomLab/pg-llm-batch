# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Low-level Postgres helpers shared by the batch core.

These wrap the handful of SQL calls the orchestrator, token counter and API
client need, so no other module has to embed connection boilerplate.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
REMOTE_TERMINAL_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})


def _require_psycopg() -> None:
    """Raise a clear error when the optional psycopg dependency is unavailable."""
    if psycopg is None:  # pragma: no cover
        raise RuntimeError("psycopg is required for database access")


def apply_schema(dsn: str, schema_path: Optional[str] = None) -> None:
    """Apply the batch DDL subset (idempotent)."""
    _require_psycopg()
    path = Path(schema_path) if schema_path else SCHEMA_PATH
    sql = path.read_text(encoding="utf-8")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def load_virtual_payload(dsn: str, file_id: str) -> Optional[str]:
    """Load a stored JSONL payload as a newline-terminated string."""
    _require_psycopg()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM llm_batch_file_payloads WHERE file_id = %s",
                (file_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _normalize_payload_content(row[0])


def _normalize_payload_content(content: Any) -> str:
    """Coerce the stored JSONB payload back into raw JSONL text."""
    if isinstance(content, dict):
        text = content.get("text", "")
    elif isinstance(content, str):
        text = content
    else:  # pragma: no cover - defensive
        text = str(content)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _provider_text(value: Any) -> Optional[str]:
    """Return a non-empty provider string or ``None`` for untrusted values."""
    return value if isinstance(value, str) and value else None


def _provider_count(value: Any) -> int:
    """Return a non-negative integer provider count or the safe default zero."""
    return value if type(value) is int and value >= 0 else 0


def persist_remote_batch_state(
    dsn: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    *,
    observed_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Atomically insert or update one curated provider batch observation.

    The unique ``(endpoint_alias, remote_batch_id)`` identity makes repeated
    polling idempotent. A stale observation cannot overwrite a newer one because
    the upsert updates only when its ``last_observed_at`` is at least as recent
    as the stored value. Only operational fields and provider metadata are
    persisted; arbitrary response fields are deliberately discarded.

    Args:
        dsn: PostgreSQL connection string for the lifecycle store.
        endpoint_alias: Stable local alias for the remote Batch API endpoint.
        provider_batch: Provider batch object containing at minimum an ``id``.
        observed_at: Optional timezone-aware observation timestamp. Current UTC
            is used when omitted.

    Returns:
        The normalized lifecycle snapshot written to PostgreSQL.

    Raises:
        ValueError: If the endpoint alias, provider object, remote identifier,
            or observation timestamp is invalid.
        RuntimeError: If psycopg is unavailable.
    """
    _require_psycopg()
    if not isinstance(endpoint_alias, str) or not endpoint_alias.strip():
        raise ValueError("endpoint_alias must be a non-empty string")
    normalized_alias = endpoint_alias.strip()
    if not isinstance(provider_batch, Mapping):
        raise ValueError("provider_batch must be a mapping object")

    remote_batch_id = provider_batch.get("id")
    if not isinstance(remote_batch_id, str) or not remote_batch_id:
        raise ValueError("provider batch id must be a non-empty string")

    observed = observed_at or datetime.now(timezone.utc)
    if (
        not isinstance(observed, datetime)
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        raise ValueError("observed_at must be a timezone-aware datetime")

    status_value = provider_batch.get("status")
    batch_status = status_value if isinstance(status_value, str) and status_value else "unknown"
    counts_value = provider_batch.get("request_counts")
    request_counts = counts_value if isinstance(counts_value, Mapping) else {}
    metadata_value = provider_batch.get("metadata")
    provider_metadata = dict(metadata_value) if isinstance(metadata_value, Mapping) else {}
    terminal_at = observed if batch_status in REMOTE_TERMINAL_STATUSES else None

    snapshot: Dict[str, Any] = {
        "endpoint_alias": normalized_alias,
        "remote_batch_id": remote_batch_id,
        "input_file_id": _provider_text(provider_batch.get("input_file_id")),
        "batch_endpoint": _provider_text(provider_batch.get("endpoint")),
        "batch_status": batch_status,
        "output_file_id": _provider_text(provider_batch.get("output_file_id")),
        "error_file_id": _provider_text(provider_batch.get("error_file_id")),
        "total_requests": _provider_count(request_counts.get("total")),
        "completed_requests": _provider_count(request_counts.get("completed")),
        "failed_requests": _provider_count(request_counts.get("failed")),
        "provider_metadata": provider_metadata,
        "observed_at": observed,
        "terminal_at": terminal_at,
    }
    metadata_json = json.dumps(
        provider_metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    sql = """
        INSERT INTO llm_remote_batch_jobs (
            endpoint_alias,
            remote_batch_id,
            input_file_id,
            batch_endpoint,
            batch_status,
            output_file_id,
            error_file_id,
            total_requests,
            completed_requests,
            failed_requests,
            provider_metadata,
            first_seen_at,
            last_observed_at,
            terminal_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s::jsonb, %s, %s, %s, %s
        )
        ON CONFLICT (endpoint_alias, remote_batch_id) DO UPDATE
        SET input_file_id = COALESCE(
                EXCLUDED.input_file_id,
                llm_remote_batch_jobs.input_file_id
            ),
            batch_endpoint = COALESCE(
                EXCLUDED.batch_endpoint,
                llm_remote_batch_jobs.batch_endpoint
            ),
            batch_status = EXCLUDED.batch_status,
            output_file_id = COALESCE(
                EXCLUDED.output_file_id,
                llm_remote_batch_jobs.output_file_id
            ),
            error_file_id = COALESCE(
                EXCLUDED.error_file_id,
                llm_remote_batch_jobs.error_file_id
            ),
            total_requests = EXCLUDED.total_requests,
            completed_requests = EXCLUDED.completed_requests,
            failed_requests = EXCLUDED.failed_requests,
            provider_metadata = CASE
                WHEN EXCLUDED.provider_metadata = '{}'::jsonb
                    THEN llm_remote_batch_jobs.provider_metadata
                ELSE EXCLUDED.provider_metadata
            END,
            last_observed_at = EXCLUDED.last_observed_at,
            terminal_at = COALESCE(
                llm_remote_batch_jobs.terminal_at,
                EXCLUDED.terminal_at
            ),
            updated_at = EXCLUDED.updated_at
        WHERE EXCLUDED.last_observed_at >= llm_remote_batch_jobs.last_observed_at
    """
    params = (
        snapshot["endpoint_alias"],
        snapshot["remote_batch_id"],
        snapshot["input_file_id"],
        snapshot["batch_endpoint"],
        snapshot["batch_status"],
        snapshot["output_file_id"],
        snapshot["error_file_id"],
        snapshot["total_requests"],
        snapshot["completed_requests"],
        snapshot["failed_requests"],
        metadata_json,
        observed,
        observed,
        terminal_at,
        observed,
    )
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    return snapshot


def get_model_metadata(dsn: Optional[str], model_id: str) -> Optional[Dict[str, Any]]:
    """Fetch model mode/tokenizer metadata for a model id, if recorded.

    Looks up the per-endpoint mapping populated by the pg_cron model-sync job.
    Returns ``{'mode': ..., 'tokenizer_model': ...}`` or None.
    """
    if not dsn or psycopg is None or not model_id:
        return None
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT model_mode, tokenizer_model
                    FROM llm_endpoint_models
                    WHERE model_id = %s
                    ORDER BY last_verified_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    (model_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                mode, tokenizer_model = row
                return {
                    "mode": (mode or "").strip().lower() if mode else None,
                    "tokenizer_model": tokenizer_model,
                }
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("model metadata lookup failed for %s: %s", model_id, exc)
        return None
