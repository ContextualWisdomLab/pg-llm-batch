# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Low-level Postgres helpers shared by the batch core.

These wrap the handful of SQL calls the orchestrator, token counter and API
client need, so no other module has to embed connection boilerplate.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .exceptions import ValidationError

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MAX_PROVIDER_METADATA_BYTES = 64 * 1024
MAX_ENDPOINT_ALIAS_CHARACTERS = 128
MAX_REMOTE_RESOURCE_ID_CHARACTERS = 256
REMOTE_RESOURCE_ID_PATTERN = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_REMOTE_RESOURCE_ID_CHARACTERS - 1}}}\Z"
)
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


def normalize_optional_provider_text(value: Any) -> Optional[str]:
    """Return NUL-free provider text or ``None`` for unsafe optional values."""
    return (
        value
        if isinstance(value, str) and value and "\x00" not in value
        else None
    )


def _provider_count(value: Any) -> int:
    """Return a non-negative integer provider count or the safe default zero."""
    return value if type(value) is int and value >= 0 else 0


def validate_endpoint_alias(value: Any) -> str:
    """Normalize one endpoint alias within the persisted schema contract.

    Endpoint aliases identify configured gateway credentials and participate in
    the durable lifecycle table's compound key. Whitespace surrounding an alias
    is ignored, while empty, NUL-containing, non-string, or overlong values fail
    before database reservation, secret resolution, or provider network activity.

    Args:
        value: Candidate endpoint alias supplied by a caller or host service.

    Returns:
        The trimmed endpoint alias.

    Raises:
        ValidationError: If the alias is not a NUL-free 1-128 character string
            after trimming.
    """
    if not isinstance(value, str):
        raise ValidationError(
            field="endpoint_alias",
            value=value,
            reason=(
                "must be a non-empty NUL-free string of at most "
                f"{MAX_ENDPOINT_ALIAS_CHARACTERS} characters"
            ),
        )
    normalized = value.strip()
    if (
        not normalized
        or "\x00" in normalized
        or len(normalized) > MAX_ENDPOINT_ALIAS_CHARACTERS
    ):
        raise ValidationError(
            field="endpoint_alias",
            value=value,
            reason=(
                "must be a non-empty NUL-free string of at most "
                f"{MAX_ENDPOINT_ALIAS_CHARACTERS} characters"
            ),
        )
    return normalized


def validate_remote_resource_id(value: Any, field: str) -> str:
    """Validate one provider identifier against the durable gateway contract.

    The supported identifier syntax is safe for URL path segments and mirrors
    the lifecycle schema's 256-character maximum. Keeping the same contract for
    caller IDs and provider-returned IDs prevents a successful remote operation
    from failing only when its durable state reaches PostgreSQL.

    Args:
        value: Candidate provider file or batch identifier.
        field: Field name included in structured validation evidence.

    Returns:
        The validated identifier without modification.

    Raises:
        ValidationError: If the value is not a supported 1-256 character ASCII
            resource identifier.
    """
    if (
        not isinstance(value, str)
        or REMOTE_RESOURCE_ID_PATTERN.fullmatch(value) is None
    ):
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


def validate_optional_remote_resource_id(
    value: Any,
    field: str,
) -> Optional[str]:
    """Normalize non-string absence and validate every present string identifier.

    Non-string values and the empty string retain the existing deterministic
    safe-default behavior for optional provider fields. Every non-empty string
    must satisfy the bounded ASCII path-segment contract used by required
    remote batch identifiers.
    """
    if not isinstance(value, str) or not value:
        return None
    return validate_remote_resource_id(value, field)


def _persisted_remote_resource_id(value: Any, field: str) -> Optional[str]:
    """Map optional identifier validation to the persistence helper contract."""
    try:
        return validate_optional_remote_resource_id(value, field)
    except ValidationError as exc:
        raise ValueError(
            f"{field} must be a supported optional remote resource identifier"
        ) from exc


def _metadata_contains_nul(value: Any) -> bool:
    """Return whether decoded JSON contains PostgreSQL-incompatible NUL text.

    The traversal is iterative so deeply nested untrusted metadata cannot spend
    Python recursion depth after the canonical JSON representation has already
    passed the 64-KiB size boundary.
    """
    pending_values = [value]
    while pending_values:
        current_value = pending_values.pop()
        if isinstance(current_value, str):
            if "\x00" in current_value:
                return True
            continue
        if isinstance(current_value, list):
            pending_values.extend(current_value)
            continue
        if isinstance(current_value, dict):
            for metadata_key, nested_value in current_value.items():
                if "\x00" in metadata_key:
                    return True
                pending_values.append(nested_value)
    return False


def _provider_metadata(value: Any) -> tuple[Dict[str, Any], str]:
    """Return bounded PostgreSQL-safe JSON metadata or the empty object."""
    if not isinstance(value, Mapping):
        return {}, "{}"
    try:
        metadata_json = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        metadata_bytes = metadata_json.encode("utf-8")
        if len(metadata_bytes) > MAX_PROVIDER_METADATA_BYTES:
            return {}, "{}"
        provider_metadata: Dict[str, Any] = json.loads(metadata_json)
    except Exception:
        return {}, "{}"
    if _metadata_contains_nul(provider_metadata):
        return {}, "{}"
    return provider_metadata, metadata_json


def normalize_provider_metadata(value: Any) -> Dict[str, Any]:
    """Return canonical provider metadata safe for PostgreSQL ``jsonb``.

    A provider metadata value is retained only when it is an object whose sorted
    compact JSON encoding is finite, serializable, no larger than 64 KiB, and
    free of U+0000 in every key and nested string. Invalid metadata becomes the
    deterministic empty object so both the default PostgreSQL recorder and
    injected host recorders observe the same fail-closed representation.

    Args:
        value: Untrusted provider metadata from a remote Batch API response.

    Returns:
        A JSON-decoded dictionary that exactly matches the canonical persisted
        representation, or an empty dictionary when validation fails.
    """
    return _provider_metadata(value)[0]


def reserve_remote_batch_observation_order(dsn: str) -> int:
    """Reserve and return one positive database-owned lifecycle order."""
    _require_psycopg()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nextval('llm_remote_batch_observation_sequence')")
            row = cur.fetchone()
    if (
        not row
        or isinstance(row[0], bool)
        or not isinstance(row[0], int)
        or row[0] <= 0
    ):
        raise RuntimeError(
            "remote batch observation sequence returned an invalid order"
        )
    return row[0]


def persist_remote_batch_state(
    dsn: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Submit one curated provider batch observation to an atomic upsert.

    The unique ``(endpoint_alias, remote_batch_id)`` identity makes repeated
    polling idempotent. The upsert accepts only a strictly newer database-owned
    ``observation_order``. Once a terminal status is stored, a later observation
    may enrich it only when the terminal status itself is unchanged. Request
    counters never decrease, so a sparse provider response cannot erase known
    progress. Arbitrary provider fields are discarded, and metadata is
    canonicalized within a bounded JSON trust boundary.

    Args:
        dsn: PostgreSQL connection string for the lifecycle store.
        endpoint_alias: Stable local alias for the remote Batch API endpoint.
        provider_batch: Provider batch object containing at minimum an ``id``.
        observation_order: Positive order reserved before the provider request.
        observed_at: Optional timezone-aware observation timestamp. Current UTC
            is used when omitted.

    Returns:
        The normalized lifecycle snapshot submitted to PostgreSQL. PostgreSQL
        may ignore the update when a newer order or incompatible terminal state
        is already stored.

    Raises:
        ValueError: If the observation order, endpoint alias, provider object,
            remote identifier, or observation timestamp is invalid.
        RuntimeError: If psycopg is unavailable.
    """
    if (
        isinstance(observation_order, bool)
        or not isinstance(observation_order, int)
        or observation_order <= 0
    ):
        raise ValueError("observation_order must be a positive integer")
    try:
        normalized_alias = validate_endpoint_alias(endpoint_alias)
    except ValidationError as exc:
        raise ValueError(
            "endpoint_alias must be a non-empty NUL-free string of at most "
            f"{MAX_ENDPOINT_ALIAS_CHARACTERS} characters"
        ) from exc
    if not isinstance(provider_batch, Mapping):
        raise ValueError("provider_batch must be a mapping object")

    try:
        remote_batch_id = validate_remote_resource_id(
            provider_batch.get("id"),
            "remote_batch_id",
        )
    except ValidationError as exc:
        raise ValueError(
            "remote_batch_id (provider batch id) must be a supported non-empty "
            f"string of at most {MAX_REMOTE_RESOURCE_ID_CHARACTERS} characters"
        ) from exc

    observed = observed_at or datetime.now(timezone.utc)
    if (
        not isinstance(observed, datetime)
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        raise ValueError("observed_at must be a timezone-aware datetime")

    input_file_id = _persisted_remote_resource_id(
        provider_batch.get("input_file_id"),
        "input_file_id",
    )
    output_file_id = _persisted_remote_resource_id(
        provider_batch.get("output_file_id"),
        "output_file_id",
    )
    error_file_id = _persisted_remote_resource_id(
        provider_batch.get("error_file_id"),
        "error_file_id",
    )
    batch_status = (
        normalize_optional_provider_text(provider_batch.get("status"))
        or "unknown"
    )
    counts_value = provider_batch.get("request_counts")
    request_counts = counts_value if isinstance(counts_value, Mapping) else {}
    provider_metadata, metadata_json = _provider_metadata(
        provider_batch.get("metadata")
    )
    terminal_at = observed if batch_status in REMOTE_TERMINAL_STATUSES else None

    snapshot: Dict[str, Any] = {
        "endpoint_alias": normalized_alias,
        "remote_batch_id": remote_batch_id,
        "observation_order": observation_order,
        "input_file_id": input_file_id,
        "batch_endpoint": normalize_optional_provider_text(
            provider_batch.get("endpoint")
        ),
        "batch_status": batch_status,
        "output_file_id": output_file_id,
        "error_file_id": error_file_id,
        "total_requests": _provider_count(request_counts.get("total")),
        "completed_requests": _provider_count(request_counts.get("completed")),
        "failed_requests": _provider_count(request_counts.get("failed")),
        "provider_metadata": provider_metadata,
        "observed_at": observed,
        "terminal_at": terminal_at,
    }

    sql = """
        INSERT INTO llm_remote_batch_jobs (
            endpoint_alias,
            remote_batch_id,
            observation_order,
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
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s::jsonb, %s, %s, %s, %s
        )
        ON CONFLICT (endpoint_alias, remote_batch_id) DO UPDATE
        SET observation_order = EXCLUDED.observation_order,
            input_file_id = COALESCE(
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
            total_requests = GREATEST(
                llm_remote_batch_jobs.total_requests,
                EXCLUDED.total_requests
            ),
            completed_requests = GREATEST(
                llm_remote_batch_jobs.completed_requests,
                EXCLUDED.completed_requests
            ),
            failed_requests = GREATEST(
                llm_remote_batch_jobs.failed_requests,
                EXCLUDED.failed_requests
            ),
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
        WHERE EXCLUDED.observation_order > llm_remote_batch_jobs.observation_order
          AND (
              llm_remote_batch_jobs.batch_status NOT IN (
                  'completed', 'failed', 'expired', 'cancelled'
              )
              OR EXCLUDED.batch_status = llm_remote_batch_jobs.batch_status
          )
    """
    params = (
        snapshot["endpoint_alias"],
        snapshot["remote_batch_id"],
        snapshot["observation_order"],
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
    _require_psycopg()
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
