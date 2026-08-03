# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Postgres batch orchestrator.

Reads queued ``llm_requests`` rows, assembles OpenAI-compatible JSONL request
lines while respecting token/byte/record limits, and persists them into
``llm_batch_file_payloads`` / ``llm_batch_files`` / ``llm_jsonl_lines`` for
JOIN-only, disk-free assembly.

Extracted and relicensed (Apache-2.0) from xtrmLLMBatchPython.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import db
from .config import PostgresConfigStore
from .exceptions import ValidationError
from .token_counter import BatchAccumulator, TokenCounter

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
    from psycopg.types.json import Jsonb  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore
    Jsonb = None  # type: ignore


def _validate_effective_token_limit(value: Optional[int]) -> Optional[int]:
    """Validate an optional stricter runtime token limit."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(
            field="effective_token_limit",
            value=value,
            reason="must be a positive integer when provided",
        )
    return value


@dataclass
class BatchPayload:
    """Describe one prepared in-memory JSONL payload."""

    file_path: str
    request_count: int
    total_tokens: int


class PostgresBatchOrchestrator:
    """Assemble and persist JSONL batch payloads from queued requests."""

    def __init__(self, dsn: str) -> None:
        """Initialize the orchestrator with an explicit PostgreSQL DSN."""
        if not dsn or psycopg is None:
            raise RuntimeError("A Postgres DSN and psycopg are required")
        self.dsn = dsn

    def _resolve_batch_uuid(self, batch_key: str) -> Optional[str]:
        """Resolve a batch UUID directly or via its input_file_path key."""
        try:
            uuid.UUID(str(batch_key))
            return str(batch_key)
        except ValueError:
            pass
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT batch_uuid FROM llm_batches "
                    "WHERE input_file_path = %s LIMIT 1",
                    (batch_key,),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None

    def prepare_batches(
        self,
        *,
        batch_uuid: str,
        effective_token_limit: Optional[int] = None,
    ) -> Dict[str, List[BatchPayload]]:
        """Create JSONL payloads once and return the persisted preparation.

        Returns a dict with ``ready`` and ``overflow`` lists of BatchPayload.
        Repeated calls return the existing preparation. Additional unassigned
        requests cannot be appended after files have been prepared.
        """
        validated_token_limit = _validate_effective_token_limit(
            effective_token_limit
        )
        resolved_uuid = self._resolve_batch_uuid(batch_uuid)
        if resolved_uuid is None:
            raise ValidationError(
                field="batch_uuid",
                value=batch_uuid,
                reason=(
                    "must be a UUID or match an existing "
                    "llm_batches.input_file_path"
                ),
            )

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT request_uuid, system_prompt, user_prompt, model_name
                    FROM llm_requests
                    WHERE request_status = 'queued'
                      AND batch_file_uuid IS NULL
                      AND batch_uuid = %s::uuid
                    ORDER BY created_at ASC
                    """,
                    (resolved_uuid,),
                )
                rows: List[Tuple] = cur.fetchall()

        config = PostgresConfigStore(self.dsn)
        counter = TokenCounter(self.dsn, config=config)
        if validated_token_limit is not None:
            counter.effective_limit = min(
                counter.effective_limit, validated_token_limit
            )

        payloads = self._assemble_payloads(counter, rows)
        return self._persist_payloads(payloads, resolved_uuid, counter)

    def _assemble_payloads(
        self, counter: TokenCounter, rows: List[Tuple]
    ) -> List[Dict[str, Any]]:
        part_index = 0
        current_model: Optional[str] = None
        acc: Optional[BatchAccumulator] = None
        payloads: List[Dict[str, Any]] = []

        for (request_uuid, system_prompt, user_prompt, model_name) in rows:
            metadata = db.get_model_metadata(self.dsn, model_name)
            mode = str((metadata or {}).get("mode") or "").lower()
            system_for_tokens = system_prompt if mode != "embedding" else ""

            if acc is not None and current_model != model_name:
                drained = acc.drain()
                if drained:  # pragma: no branch - accumulator has the prior row
                    payloads.append({"part_index": part_index, **drained})
                    part_index += 1
                acc = None

            if acc is None:
                acc = BatchAccumulator(counter, model_name)
                current_model = model_name

            total_tokens, _, _ = acc.compute_tokens(
                system_for_tokens, user_prompt or ""
            )
            json_entry = self._build_json_entry(
                str(request_uuid), model_name, mode, system_for_tokens, user_prompt
            )
            line = json.dumps(json_entry, ensure_ascii=False)
            byte_size = BatchAccumulator.compute_byte_size(line)

            if acc.would_exceed(total_tokens, byte_size):
                drained = acc.drain()
                if drained:  # pragma: no branch - would_exceed requires a prior row
                    payloads.append({"part_index": part_index, **drained})
                    part_index += 1
                    acc = BatchAccumulator(counter, model_name)

            acc.add_entry(str(request_uuid), line, total_tokens, byte_size)

        if acc and acc.record_count > 0:
            drained = acc.drain()
            if drained:  # pragma: no branch - positive record_count implies entries
                payloads.append({"part_index": part_index, **drained})

        return payloads

    @staticmethod
    def _build_json_entry(
        request_id: str,
        model_name: str,
        mode: str,
        system_for_tokens: str,
        user_prompt: Optional[str],
    ) -> Dict[str, Any]:
        if mode == "embedding":
            return {
                "custom_id": request_id,
                "method": "POST",
                "url": "/v1/embeddings",
                "body": {"model": model_name, "input": user_prompt},
            }
        messages: List[Dict[str, str]] = []
        if system_for_tokens:
            messages.append({"role": "system", "content": system_for_tokens})
        messages.append({"role": "user", "content": user_prompt or ""})
        return {
            "custom_id": request_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {"model": model_name, "messages": messages},
        }

    @staticmethod
    def _batch_lock_key(batch_uuid: str) -> int:
        """Derive a stable positive advisory-lock key from a batch UUID."""
        return uuid.UUID(batch_uuid).int & 0x7FFF_FFFF_FFFF_FFFF

    @staticmethod
    def _categorize_existing_payloads(
        rows: List[Tuple], immediate_limit: int
    ) -> Dict[str, List[BatchPayload]]:
        """Convert persisted file rows into ready and overflow payload lists."""
        ready: List[BatchPayload] = []
        overflow: List[BatchPayload] = []
        for file_path, request_count, total_tokens, part_index in rows:
            payload = BatchPayload(
                file_path=str(file_path),
                request_count=int(request_count),
                total_tokens=int(total_tokens),
            )
            target = ready if int(part_index) < immediate_limit else overflow
            target.append(payload)
        return {"ready": ready, "overflow": overflow}

    def _load_existing_payloads(
        self,
        cur: Any,
        batch_uuid: str,
        immediate_limit: int,
    ) -> Optional[Dict[str, List[BatchPayload]]]:
        cur.execute(
            """
            SELECT file_path, request_count, total_tokens, part_index
            FROM llm_batch_files
            WHERE batch_uuid = %s::uuid
            ORDER BY part_index ASC, created_at ASC
            """,
            (batch_uuid,),
        )
        rows = cur.fetchall()
        if not rows:
            return None
        return self._categorize_existing_payloads(rows, immediate_limit)

    def _persist_payloads(
        self,
        payloads: List[Dict[str, Any]],
        batch_uuid: str,
        counter: TokenCounter,
    ) -> Dict[str, List[BatchPayload]]:
        ready: List[BatchPayload] = []
        overflow: List[BatchPayload] = []
        immediate_limit = counter.azure_max_files_per_job
        lock_key = self._batch_lock_key(batch_uuid)

        with psycopg.connect(self.dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
                cur.execute(
                    "SELECT queue_uuid FROM llm_batches "
                    "WHERE batch_uuid = %s::uuid FOR UPDATE",
                    (batch_uuid,),
                )
                batch_row = cur.fetchone()
                if batch_row is None:
                    raise ValidationError(
                        field="batch_uuid",
                        value=batch_uuid,
                        reason="batch disappeared before preparation could be persisted",
                    )
                queue_uuid = batch_row[0]

                existing = self._load_existing_payloads(
                    cur, batch_uuid, immediate_limit
                )
                if existing is not None:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM llm_requests
                            WHERE batch_uuid = %s::uuid
                              AND request_status = 'queued'
                              AND batch_file_uuid IS NULL
                        )
                        """,
                        (batch_uuid,),
                    )
                    queued_row = cur.fetchone()
                    has_unassigned = bool(queued_row and queued_row[0])
                    if has_unassigned:
                        raise ValidationError(
                            field="batch_uuid",
                            value=batch_uuid,
                            reason=(
                                "batch already has prepared files; additional "
                                "queued requests require a new batch"
                            ),
                        )
                    conn.commit()
                    return existing

                for idx, meta in enumerate(payloads):
                    file_id = f"file_{uuid.uuid4().hex[:12]}"
                    lines = meta.get("lines", [])
                    request_ids = [str(item) for item in meta.get("request_ids", [])]
                    content = "\n".join(lines) + ("\n" if lines else "")
                    payload_doc = {"text": content, "line_count": len(lines)}
                    adapted = (
                        Jsonb(payload_doc)
                        if Jsonb is not None
                        else json.dumps(payload_doc)
                    )
                    cur.execute(
                        """
                        INSERT INTO llm_batch_file_payloads (file_id, content)
                        VALUES (%s, %s)
                        ON CONFLICT (file_id) DO UPDATE SET
                            content = EXCLUDED.content,
                            updated_at = NOW()
                        """,
                        (file_id, adapted),
                    )
                    file_path = f"memory://{file_id}"
                    cur.execute(
                        """
                        INSERT INTO llm_batch_files (
                            batch_uuid, queue_uuid, file_path, storage_ref,
                            part_index, request_count, total_tokens, payload_file_id
                        ) VALUES (
                            %s::uuid, %s, %s, NULL, %s, %s, %s, %s
                        )
                        RETURNING file_uuid
                        """,
                        (
                            batch_uuid,
                            queue_uuid,
                            file_path,
                            int(meta["part_index"]),
                            int(meta["record_count"]),
                            int(meta["total_tokens"]),
                            file_id,
                        ),
                    )
                    file_row = cur.fetchone()
                    if file_row is None:
                        raise RuntimeError("Persisted batch file did not return file_uuid")
                    file_uuid = str(file_row[0])

                    batch_params = [
                        (rid, file_id, int(seq_no), line_txt)
                        for seq_no, (rid, line_txt) in enumerate(
                            zip(request_ids, lines), start=1
                        )
                    ]
                    if batch_params:
                        cur.executemany(
                            """
                            INSERT INTO llm_jsonl_lines
                                (request_uuid, payload_file_id, sequence_no, line_text)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            batch_params,
                        )
                        cur.execute(
                            """
                            UPDATE llm_requests
                            SET batch_file_uuid = %s::uuid
                            WHERE batch_uuid = %s::uuid
                              AND request_uuid = ANY(%s::uuid[])
                              AND request_status = 'queued'
                              AND batch_file_uuid IS NULL
                            """,
                            (file_uuid, batch_uuid, request_ids),
                        )
                        if cur.rowcount != len(request_ids):
                            raise ValidationError(
                                field="request_ids",
                                value=request_ids,
                                reason=(
                                    "queued request assignment changed during "
                                    "batch preparation"
                                ),
                            )

                    payload = BatchPayload(
                        file_path=file_path,
                        request_count=int(meta["record_count"]),
                        total_tokens=int(meta["total_tokens"]),
                    )
                    (ready if idx < immediate_limit else overflow).append(payload)

                cur.execute(
                    """
                    UPDATE llm_batches
                    SET total_requests = %s,
                        total_tokens = %s,
                        updated_at = NOW()
                    WHERE batch_uuid = %s::uuid
                    """,
                    (
                        sum(item.request_count for item in ready + overflow),
                        sum(item.total_tokens for item in ready + overflow),
                        batch_uuid,
                    ),
                )
            conn.commit()

        return {"ready": ready, "overflow": overflow}
