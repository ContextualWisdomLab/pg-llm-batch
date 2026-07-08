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
from .token_counter import BatchAccumulator, TokenCounter

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
    from psycopg.types.json import Jsonb  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore
    Jsonb = None  # type: ignore


@dataclass
class BatchPayload:
    file_path: str
    request_count: int
    total_tokens: int


class PostgresBatchOrchestrator:
    """Assemble and persist JSONL batch payloads from queued requests."""

    def __init__(self, dsn: str) -> None:
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
        """Create JSONL payloads for a batch and register their metadata.

        Returns a dict with ``ready`` and ``overflow`` lists of BatchPayload.
        """
        resolved_uuid = self._resolve_batch_uuid(batch_uuid) or batch_uuid

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT request_uuid, system_prompt, user_prompt, model_name
                    FROM llm_requests
                    WHERE request_status = 'queued' AND batch_uuid = (
                        SELECT COALESCE(%s::uuid, batch_uuid) FROM llm_batches
                        WHERE input_file_path = %s OR batch_uuid::text = %s LIMIT 1
                    )
                    ORDER BY created_at ASC
                    """,
                    (resolved_uuid, batch_uuid, batch_uuid),
                )
                rows: List[Tuple] = cur.fetchall()

        config = PostgresConfigStore(self.dsn)
        counter = TokenCounter(self.dsn, config=config)
        if effective_token_limit is not None:
            counter.effective_limit = min(
                counter.effective_limit, int(effective_token_limit)
            )

        payloads = self._assemble_payloads(counter, rows)
        return self._persist_payloads(payloads, batch_uuid, counter)

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

            if acc is None or current_model != model_name:
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
                if drained:
                    payloads.append({"part_index": part_index, **drained})
                    part_index += 1
                    acc = BatchAccumulator(counter, model_name)

            acc.add_entry(str(request_uuid), line, total_tokens, byte_size)

        if acc and acc.record_count > 0:
            drained = acc.drain()
            if drained:
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

    def _persist_payloads(
        self,
        payloads: List[Dict[str, Any]],
        batch_uuid: str,
        counter: TokenCounter,
    ) -> Dict[str, List[BatchPayload]]:
        ready: List[BatchPayload] = []
        overflow: List[BatchPayload] = []
        immediate_limit = counter.azure_max_files_per_job

        with psycopg.connect(self.dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                for idx, meta in enumerate(payloads):
                    file_id = f"file_{uuid.uuid4().hex[:12]}"
                    lines = meta.get("lines", [])
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
                            (SELECT batch_uuid FROM llm_batches
                             WHERE input_file_path = %s OR batch_uuid::text = %s
                             LIMIT 1),
                            (SELECT queue_uuid FROM llm_batches
                             WHERE input_file_path = %s OR batch_uuid::text = %s
                             LIMIT 1),
                            %s, NULL, %s, %s, %s, %s
                        )
                        """,
                        (
                            batch_uuid,
                            batch_uuid,
                            batch_uuid,
                            batch_uuid,
                            file_path,
                            int(meta["part_index"]),
                            int(meta["record_count"]),
                            int(meta["total_tokens"]),
                            file_id,
                        ),
                    )
                    batch_params = [
                        (rid, file_id, int(seq_no), line_txt)
                        for seq_no, (rid, line_txt) in enumerate(
                            zip(meta.get("request_ids", []), lines), start=1
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
                    payload = BatchPayload(
                        file_path=file_path,
                        request_count=int(meta["record_count"]),
                        total_tokens=int(meta["total_tokens"]),
                    )
                    (ready if idx < immediate_limit else overflow).append(payload)
            conn.commit()

        return {"ready": ready, "overflow": overflow}
