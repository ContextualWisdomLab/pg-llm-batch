# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Low-level Postgres helpers shared by the batch core.

These helpers wrap the SQL calls needed by the orchestrator, token counter, and
Batch API clients. Durable provider lifecycle state supports both standalone
operation and trusted tenant-scoped shared-table deployments.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Dict, Optional

from .exceptions import ValidationError
from .postgres_driver_port import PostgresDriverPort
from .postgres_driver_runtime import retained_postgres_driver

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MAX_PROVIDER_METADATA_BYTES = 64 * 1024
MAX_ENDPOINT_ALIAS_CHARACTERS = 128
MAX_REMOTE_RESOURCE_ID_CHARACTERS = 256
MAX_TENANT_SCOPE_CHARACTERS = 128
DEFAULT_TENANT_SCOPE = "standalone"
REMOTE_RESOURCE_ID_PATTERN = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_REMOTE_RESOURCE_ID_CHARACTERS - 1}}}\Z"
)
TENANT_SCOPE_PATTERN = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_TENANT_SCOPE_CHARACTERS - 1}}}\Z"
)
SUPPORTED_REMOTE_BATCH_STATUSES = frozenset(
    {
        "validating",
        "failed",
        "in_progress",
        "finalizing",
        "completed",
        "expired",
        "cancelling",
        "cancelled",
    }
)
SUPPORTED_REMOTE_BATCH_ENDPOINTS = frozenset(
    {
        "/v1/responses",
        "/v1/chat/completions",
        "/v1/embeddings",
        "/v1/completions",
        "/v1/moderations",
    }
)
REMOTE_TERMINAL_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})
_REMOTE_BATCH_STATE_FIELDS = (
    "tenant_scope",
    "endpoint_alias",
    "remote_batch_id",
    "observation_order",
    "input_file_id",
    "batch_endpoint",
    "batch_status",
    "output_file_id",
    "error_file_id",
    "total_requests",
    "completed_requests",
    "failed_requests",
    "provider_metadata",
    "first_seen_at",
    "last_observed_at",
    "terminal_at",
    "updated_at",
)


class VirtualPayloadIntegrityError(RuntimeError):
    """Signal that package-owned persisted virtual JSONL failed validation."""

    def __init__(self) -> None:
        """Create the fixed content-free durable-payload integrity error."""
        super().__init__("Stored virtual payload failed integrity validation")


def _connect_database(
    dsn: str,
    postgres_driver: PostgresDriverPort | None,
) -> Any:
    """Open one connection through the selected PostgreSQL driver boundary.

    Explicitly injected migration drivers remain authoritative for candidate and
    degraded-mode tests. When no driver is injected, one centralized runtime
    selector supplies the retained implementation so bounded contexts no longer
    import or construct Psycopg directly.
    """
    selected_driver = postgres_driver or retained_postgres_driver()
    return selected_driver.connect(dsn)


def apply_schema(
    dsn: str,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> None:
    """Apply the package-owned schema through the selected PostgreSQL driver."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with _connect_database(dsn, postgres_driver) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def load_virtual_payload(
    dsn: str,
    file_id: str,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> Optional[str]:
    """Load canonical package JSONL through the selected PostgreSQL driver."""
    with _connect_database(dsn, postgres_driver) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM llm_batch_file_payloads WHERE file_id = %s",
                (file_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _normalize_payload_content(row[0])


def _json_object_without_duplicate_members(pairs: list[tuple[str, Any]]) -> Dict[str, Any]:
    """Build one JSON object while rejecting duplicate member names."""
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _finite_json_float(token: str) -> float:
    """Parse one JSON float while rejecting exponent overflow to infinity."""
    value = float(token)
    if not isfinite(value):
        raise ValueError("non-finite JSON float")
    return value


def _reject_json_constant(_token: str) -> None:
    """Reject JSON decoder extensions such as NaN and Infinity."""
    raise ValueError("non-finite JSON constant")


def _is_canonical_json_object_line(line: str) -> bool:
    """Return whether one persisted JSONL line is a strict finite JSON object."""
    try:
        parsed = json.loads(
            line,
            object_pairs_hook=_json_object_without_duplicate_members,
            parse_float=_finite_json_float,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError, RecursionError):
        return False
    return type(parsed) is dict


def _normalize_payload_content(content: Any) -> str:
    """Validate canonical persisted JSONL and return its exact stored text."""
    valid_shape = type(content) is dict and set(content) == {"text", "line_count"}
    if not valid_shape:
        raise VirtualPayloadIntegrityError()
    text = content["text"]
    line_count = content["line_count"]
    if type(text) is not str or type(line_count) is not int or line_count < 0:
        raise VirtualPayloadIntegrityError()
    if line_count == 0:
        if text != "":
            raise VirtualPayloadIntegrityError()
        return text
    if not text.endswith("\n"):
        raise VirtualPayloadIntegrityError()
    lines = text[:-1].split("\n")
    if (
        len(lines) != line_count
        or any(not line for line in lines)
        or any(not _is_canonical_json_object_line(line) for line in lines)
    ):
        raise VirtualPayloadIntegrityError()
    return text


def normalize_optional_provider_text(value: Any) -> Optional[str]:
    """Return NUL-free provider text or ``None`` for unsafe optional values."""
    return (
        value
        if isinstance(value, str) and value and "\x00" not in value
        else None
    )


def _provider_batch_status(value: Any) -> str:
    """Return one verified durable lifecycle status or the sparse safe default."""
    if value is None or value == "":
        return "unknown"
    if type(value) is not str or value not in SUPPORTED_REMOTE_BATCH_STATUSES:
        raise ValueError("batch_status is not a supported provider status")
    return value


def _provider_batch_endpoint(value: Any) -> Optional[str]:
    """Return one verified durable batch endpoint or preserve sparse absence."""
    if value is None or value == "":
        return None
    if type(value) is not str or value not in SUPPORTED_REMOTE_BATCH_ENDPOINTS:
        raise ValueError(
            "batch_endpoint is not a supported provider batch endpoint"
        )
    return value


def _provider_count(value: Any) -> int:
    """Return a non-negative integer provider count or the safe default zero."""
    return value if type(value) is int and value >= 0 else 0


def validate_endpoint_alias(value: Any) -> str:
    """Normalize one endpoint alias within the persisted schema contract.

    Endpoint aliases identify configured gateway credentials and participate in
    the durable lifecycle table's compound key. Surrounding whitespace is
    ignored, while empty, NUL-containing, non-string, or overlong values fail
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


def validate_tenant_scope(value: Any) -> str:
    """Validate one trusted local tenant scope without trimming or coercion.

    Tenant scope must be selected by the embedding host after authentication and
    authorization. Provider metadata, remote identifiers, request payloads, and
    transport headers are not tenant authorities.

    Args:
        value: Host-authorized tenant identity for lifecycle isolation.

    Returns:
        The exact validated ASCII tenant scope.

    Raises:
        ValidationError: If the value is not a supported 1-128 character scope.
    """
    if not isinstance(value, str) or TENANT_SCOPE_PATTERN.fullmatch(value) is None:
        raise ValidationError(
            field="tenant_scope",
            value=value,
            reason=(
                "must be 1-128 ASCII characters beginning with an alphanumeric "
                "character and containing only letters, digits, dot, underscore, "
                "colon, or hyphen"
            ),
        )
    return value


def validate_remote_resource_id(value: Any, field: str) -> str:
    """Validate one provider identifier against the durable gateway contract.

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
    """Normalize absence and validate every present string identifier."""
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
    """Return whether decoded JSON contains PostgreSQL-incompatible NUL text."""
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

    Args:
        value: Untrusted provider metadata from a remote Batch API response.

    Returns:
        A bounded, finite, NUL-free JSON object or an empty dictionary.
    """
    return _provider_metadata(value)[0]


def reserve_remote_batch_observation_order(
    dsn: str,
    *,
    tenant_scope: str = DEFAULT_TENANT_SCOPE,
    postgres_driver: PostgresDriverPort | None = None,
) -> int:
    """Reserve one positive lifecycle order after binding validated tenant scope."""
    normalized_tenant_scope = validate_tenant_scope(tenant_scope)
    with _connect_database(dsn, postgres_driver) as conn:
        with conn.cursor() as cur:
            _set_transaction_tenant_scope(cur, normalized_tenant_scope)
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


def _set_transaction_tenant_scope(cursor: Any, tenant_scope: str) -> None:
    """Bind one validated tenant scope to only the current transaction."""
    cursor.execute(
        "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
        (tenant_scope,),
    )


def _cursor_row_count(
    cursor: Any,
    _postgres_driver: PostgresDriverPort | None,
) -> int | None:
    """Read an exact affected-row count through a driver-neutral cursor surface."""
    row_count = getattr(cursor, "row_count", None)
    value = row_count() if callable(row_count) else getattr(cursor, "rowcount", None)
    if value is None or value == -1:
        return None
    if type(value) is not int or value < 0:
        return None
    return value


def _normalize_remote_batch_snapshot(
    tenant_scope: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    observed_at: Optional[datetime],
) -> tuple[Dict[str, Any], str]:
    """Validate and normalize one tenant-qualified provider observation."""
    normalized_tenant_scope = validate_tenant_scope(tenant_scope)
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
    batch_status = _provider_batch_status(provider_batch.get("status"))
    batch_endpoint = _provider_batch_endpoint(provider_batch.get("endpoint"))
    counts_value = provider_batch.get("request_counts")
    request_counts = counts_value if isinstance(counts_value, Mapping) else {}
    raw_total_requests = request_counts.get("total")
    total_requests_known = (
        type(raw_total_requests) is int and raw_total_requests >= 0
    )
    total_requests = _provider_count(raw_total_requests)
    completed_requests = _provider_count(request_counts.get("completed"))
    failed_requests = _provider_count(request_counts.get("failed"))
    if (
        total_requests_known
        and completed_requests + failed_requests > total_requests
    ):
        raise ValueError("request_counts progress is inconsistent")
    provider_metadata, metadata_json = _provider_metadata(
        provider_batch.get("metadata")
    )
    terminal_at = observed if batch_status in REMOTE_TERMINAL_STATUSES else None
    snapshot: Dict[str, Any] = {
        "tenant_scope": normalized_tenant_scope,
        "endpoint_alias": normalized_alias,
        "remote_batch_id": remote_batch_id,
        "observation_order": observation_order,
        "input_file_id": input_file_id,
        "batch_endpoint": batch_endpoint,
        "batch_status": batch_status,
        "output_file_id": output_file_id,
        "error_file_id": error_file_id,
        "total_requests": total_requests,
        "total_requests_known": total_requests_known,
        "completed_requests": completed_requests,
        "failed_requests": failed_requests,
        "provider_metadata": provider_metadata,
        "observed_at": observed,
        "terminal_at": terminal_at,
    }
    return snapshot, metadata_json


def _persist_remote_batch_state(
    dsn: str,
    tenant_scope: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: Optional[datetime] = None,
    postgres_driver: PostgresDriverPort | None = None,
) -> Dict[str, Any]:
    """Persist one validated tenant lifecycle projection through the driver port."""
    snapshot, metadata_json = _normalize_remote_batch_snapshot(
        tenant_scope,
        endpoint_alias,
        provider_batch,
        observation_order,
        observed_at,
    )
    observed = snapshot["observed_at"]
    terminal_at = snapshot["terminal_at"]
    sql = """
        INSERT INTO llm_remote_batch_jobs (
            tenant_scope,
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
            total_requests_known,
            first_seen_at,
            last_observed_at,
            terminal_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s::jsonb, %s, %s, %s, %s, %s
        )
        ON CONFLICT (tenant_scope, endpoint_alias, remote_batch_id) DO UPDATE
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
            total_requests_known = (
                llm_remote_batch_jobs.total_requests_known
                OR EXCLUDED.total_requests_known
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
              NOT (
                  llm_remote_batch_jobs.total_requests_known
                  OR EXCLUDED.total_requests_known
              )
              OR GREATEST(
                  llm_remote_batch_jobs.completed_requests,
                  EXCLUDED.completed_requests
              ) + GREATEST(
                  llm_remote_batch_jobs.failed_requests,
                  EXCLUDED.failed_requests
              ) <= GREATEST(
                  llm_remote_batch_jobs.total_requests,
                  EXCLUDED.total_requests
              )
          )
          AND (
              llm_remote_batch_jobs.batch_status NOT IN (
                  'completed', 'failed', 'expired', 'cancelled'
              )
              OR EXCLUDED.batch_status = llm_remote_batch_jobs.batch_status
          )
    """
    params = (
        snapshot["tenant_scope"],
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
        snapshot["total_requests_known"],
        observed,
        observed,
        terminal_at,
        observed,
    )
    with _connect_database(dsn, postgres_driver) as conn:
        with conn.cursor() as cur:
            _set_transaction_tenant_scope(cur, snapshot["tenant_scope"])
            cur.execute(sql, params)
            affected_rows = _cursor_row_count(cur, postgres_driver)
            if affected_rows in (None, 0):
                cur.execute(
                    """
                    SELECT tenant_scope,
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
                    FROM llm_remote_batch_jobs
                    WHERE tenant_scope = %s
                      AND endpoint_alias = %s
                      AND remote_batch_id = %s
                    """,
                    (
                        snapshot["tenant_scope"],
                        snapshot["endpoint_alias"],
                        snapshot["remote_batch_id"],
                    ),
                )
                persisted_row = cur.fetchone()
                if (
                    not persisted_row
                    or len(persisted_row) != len(_REMOTE_BATCH_STATE_FIELDS)
                ):
                    raise RuntimeError(
                        "remote batch progress update was rejected without persisted state"
                    )
                snapshot = dict(zip(_REMOTE_BATCH_STATE_FIELDS, persisted_row))
        conn.commit()
    return snapshot


def persist_remote_batch_state(
    dsn: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: Optional[datetime] = None,
    postgres_driver: PostgresDriverPort | None = None,
) -> Dict[str, Any]:
    """Persist one standalone projection through the selected PostgreSQL driver."""
    snapshot = _persist_remote_batch_state(
        dsn,
        DEFAULT_TENANT_SCOPE,
        endpoint_alias,
        provider_batch,
        observation_order,
        observed_at=observed_at,
        postgres_driver=postgres_driver,
    )
    snapshot.pop("tenant_scope", None)
    snapshot.pop("total_requests_known", None)
    return snapshot


def persist_tenant_remote_batch_state(
    dsn: str,
    tenant_scope: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: Optional[datetime] = None,
    postgres_driver: PostgresDriverPort | None = None,
) -> Dict[str, Any]:
    """Persist one trusted-tenant lifecycle projection through the driver port."""
    snapshot = _persist_remote_batch_state(
        dsn,
        tenant_scope,
        endpoint_alias,
        provider_batch,
        observation_order,
        observed_at=observed_at,
        postgres_driver=postgres_driver,
    )
    snapshot.pop("total_requests_known", None)
    return snapshot


def get_tenant_remote_batch_state(
    dsn: str,
    tenant_scope: str,
    endpoint_alias: str,
    remote_batch_id: str,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> Optional[Dict[str, Any]]:
    """Return one tenant-visible lifecycle projection through the driver port."""
    normalized_tenant_scope = validate_tenant_scope(tenant_scope)
    normalized_alias = validate_endpoint_alias(endpoint_alias)
    normalized_remote_batch_id = validate_remote_resource_id(
        remote_batch_id,
        "remote_batch_id",
    )
    sql = """
        SELECT tenant_scope,
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
        FROM llm_remote_batch_jobs
        WHERE tenant_scope = %s
          AND endpoint_alias = %s
          AND remote_batch_id = %s
    """
    with _connect_database(dsn, postgres_driver) as conn:
        with conn.cursor() as cur:
            _set_transaction_tenant_scope(cur, normalized_tenant_scope)
            cur.execute(
                sql,
                (
                    normalized_tenant_scope,
                    normalized_alias,
                    normalized_remote_batch_id,
                ),
            )
            row = cur.fetchone()
    if not row:
        return None
    if len(row) != len(_REMOTE_BATCH_STATE_FIELDS):
        raise RuntimeError("remote batch state query returned an invalid row")
    return dict(zip(_REMOTE_BATCH_STATE_FIELDS, row))


def get_remote_batch_state(
    dsn: str,
    endpoint_alias: str,
    remote_batch_id: str,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> Optional[Dict[str, Any]]:
    """Return one standalone lifecycle projection through the driver port."""
    return get_tenant_remote_batch_state(
        dsn,
        DEFAULT_TENANT_SCOPE,
        endpoint_alias,
        remote_batch_id,
        postgres_driver=postgres_driver,
    )


def get_model_metadata(
    dsn: Optional[str],
    model_id: str,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> Optional[Dict[str, Any]]:
    """Fetch model metadata through the selected PostgreSQL driver boundary.

    Args:
        dsn: Optional PostgreSQL connection string.
        model_id: Provider model identifier to resolve.
        postgres_driver: Optional migration driver retained only for database I/O.

    Returns:
        A dictionary containing normalized ``mode`` and ``tokenizer_model`` when
        found, otherwise ``None``.
    """
    if not dsn or not model_id:
        return None
    try:
        with _connect_database(dsn, postgres_driver) as conn:
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
