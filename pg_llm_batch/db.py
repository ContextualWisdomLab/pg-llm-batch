# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Low-level Postgres helpers shared by the batch core.

These wrap the handful of SQL calls the orchestrator, token counter and API
client need, so no other module has to embed connection boilerplate.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _require_psycopg() -> None:
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
