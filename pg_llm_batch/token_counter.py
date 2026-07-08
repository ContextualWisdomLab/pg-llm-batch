# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""pg_tiktoken-backed token counting and batch accumulation.

Extracted and relicensed (Apache-2.0) from xtrmLLMBatchPython. Token counting
runs *inside* Postgres via the ``pg_tiktoken`` extension (``tiktoken_count`` /
``tiktoken_encode``); there is no Python-side tokenizer fallback, so counts are
identical to what the database uses when assembling batches.

Config (limits, buffers) is read from the KV config store, never from
``os.getenv``. The DSN is passed in explicitly by the caller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

from .db import get_model_metadata
from .exceptions import TokenLimitExceededError, ValidationError
from .models import BatchRequest

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
    from psycopg.errors import UndefinedFunction  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore
    UndefinedFunction = Exception  # type: ignore


@dataclass(frozen=True)
class _EncoderInfo:
    tokenizer_name: str


class TokenCounter:
    """pg_tiktoken token counter (PostgreSQL-only)."""

    DEFAULT_MAX_TOKENS_PER_BATCH = 5_000_000_000
    DEFAULT_BUFFER_PERCENTAGE = 5
    DEFAULT_MODEL_LIMIT = 128_000
    DEFAULT_AZURE_MAX_RECORDS = 100_000
    DEFAULT_AZURE_MAX_BYTES = 200 * 1024 * 1024
    DEFAULT_AZURE_MAX_FILES = 500
    FALLBACK_MULTIPLIER = 20
    MAX_REQUESTS_PER_INTERNAL_BATCH = 50

    def __init__(
        self,
        postgres_dsn: str,
        *,
        config: Optional[Any] = None,
        buffer_percentage: Optional[int] = None,
    ) -> None:
        if not postgres_dsn:
            raise ValidationError(
                field="postgres_dsn",
                value=postgres_dsn,
                reason="A Postgres DSN is required (no os.getenv fallback)",
            )
        self.postgres_dsn = postgres_dsn
        self.config = config
        self._pg_conn: Optional["psycopg.Connection"] = None
        self._pg_available: bool = False
        if psycopg is not None:
            self._pg_available = self._ensure_pg_tiktoken()
        self._encoder_cache: Dict[str, _EncoderInfo] = {}

        resolved_buffer = buffer_percentage
        if resolved_buffer is None:
            resolved_buffer = self._resolve_config_value(
                "token_limits", "buffer_percentage", self.DEFAULT_BUFFER_PERCENTAGE
            )
        if not 0 <= resolved_buffer <= 50:
            raise ValidationError(
                field="buffer_percentage",
                value=resolved_buffer,
                reason="buffer percentage must be between 0 and 50",
            )
        self.buffer_percentage = resolved_buffer

        max_tokens_per_batch = self._resolve_config_value(
            "token_limits", "per_batch", self.DEFAULT_MAX_TOKENS_PER_BATCH
        )
        self.token_limit = max_tokens_per_batch
        self.effective_limit = int(
            max_tokens_per_batch * (1 - self.buffer_percentage / 100)
        )
        self.default_model_limit = self._resolve_config_value(
            "token_limits", "per_request", self.DEFAULT_MODEL_LIMIT
        )
        self.azure_max_records_per_file = self._resolve_config_value(
            "azure_limits", "max_records_per_file", self.DEFAULT_AZURE_MAX_RECORDS
        )
        self.azure_max_bytes_per_file = self._resolve_config_value(
            "azure_limits", "max_bytes_per_file", self.DEFAULT_AZURE_MAX_BYTES
        )
        self.azure_max_files_per_job = self._resolve_config_value(
            "azure_limits", "max_files_per_job", self.DEFAULT_AZURE_MAX_FILES
        )

    # ------------------------------------------------------------------
    # Tokenizer resolution
    # ------------------------------------------------------------------
    def get_tiktoken_name(self, model: str) -> str:
        """Return the tiktoken encoding/model name for ``model``.

        Prefers the DB tokenizer mapping; falls back to the model name, which
        pg_tiktoken maps to a built-in encoding.
        """
        tokenizer_name = self._get_tokenizer_from_db(model)
        if tokenizer_name:
            return tokenizer_name
        logger.debug(
            "No DB tokenizer mapping for '%s'; using model name with pg_tiktoken "
            "built-in mapping",
            model,
        )
        return model

    def get_encoder(self, model: str) -> _EncoderInfo:
        cached = self._encoder_cache.get(model)
        if cached:
            return cached
        info = _EncoderInfo(tokenizer_name=self.get_tiktoken_name(model))
        self._encoder_cache[model] = info
        return info

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------
    def count_tokens(self, text: str, model: str) -> int:
        if not text:
            return 0
        if self._pg_available:
            try:
                return self._count_tokens_postgres(text, model)
            except UndefinedFunction:
                self._pg_available = False
                logger.warning("pg_tiktoken extension/functions unavailable")
            except Exception as exc:  # pragma: no cover - runtime DB variance
                logger.debug("PostgreSQL token counting failed: %s", exc)
        raise RuntimeError(
            "Token counting requires pg_tiktoken. Enable the extension and pass a "
            "valid DSN."
        )

    def count_request_tokens(self, request: BatchRequest) -> Tuple[int, int, int]:
        system_tokens = self.count_tokens(request.system_prompt or "", request.model)
        user_tokens = self.count_tokens(request.user_prompt, request.model)
        return system_tokens, user_tokens, system_tokens + user_tokens

    def count_batch_tokens(self, requests: List[BatchRequest]) -> Dict[str, Any]:
        if not requests:
            return {
                "total_tokens": 0,
                "total_system_tokens": 0,
                "total_user_tokens": 0,
                "request_count": 0,
                "average_tokens_per_request": 0,
                "max_tokens_per_request": 0,
                "min_tokens_per_request": 0,
                "token_breakdown": [],
            }

        token_breakdown = []
        for request in requests:
            system_tokens, user_tokens, total = self.count_request_tokens(request)
            token_breakdown.append(
                {
                    "request_id": request.id,
                    "system_tokens": system_tokens,
                    "user_tokens": user_tokens,
                    "total_tokens": total,
                    "model": request.model,
                }
            )

        total_system = sum(i["system_tokens"] for i in token_breakdown)
        total_user = sum(i["user_tokens"] for i in token_breakdown)
        total_tokens = total_system + total_user
        counts = [i["total_tokens"] for i in token_breakdown]

        if total_tokens > self.effective_limit:
            raise TokenLimitExceededError(
                current_tokens=total_tokens,
                limit_tokens=self.effective_limit,
            )

        return {
            "total_tokens": total_tokens,
            "total_system_tokens": total_system,
            "total_user_tokens": total_user,
            "request_count": len(requests),
            "average_tokens_per_request": total_tokens / len(requests),
            "max_tokens_per_request": max(counts),
            "min_tokens_per_request": min(counts),
            "token_breakdown": token_breakdown,
        }

    def split_oversized_batch(
        self, requests: List[BatchRequest]
    ) -> List[List[BatchRequest]]:
        """Split a request list so each chunk stays under the effective limit."""
        if not requests:
            return []
        batches: List[List[BatchRequest]] = []
        current: List[BatchRequest] = []
        current_tokens = 0
        for request in requests:
            _, _, request_tokens = self.count_request_tokens(request)
            if request_tokens > self.effective_limit:
                raise TokenLimitExceededError(
                    current_tokens=request_tokens,
                    limit_tokens=self.effective_limit,
                    batch_id="oversized_request",
                )
            if current and (
                current_tokens + request_tokens > self.effective_limit
                or len(current) >= self.MAX_REQUESTS_PER_INTERNAL_BATCH
            ):
                batches.append(current)
                current = [request]
                current_tokens = request_tokens
            else:
                current.append(request)
                current_tokens += request_tokens
        if current:
            batches.append(current)
        return batches

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------
    def _resolve_config_value(self, category: str, key: str, default: Any) -> Any:
        if self.config is not None:
            try:
                value = self.config.get(category, key, default)
                return value if value is not None else default
            except Exception:
                return default
        return default

    # ------------------------------------------------------------------
    # pg_tiktoken plumbing
    # ------------------------------------------------------------------
    def _ensure_pg_tiktoken(self) -> bool:
        if psycopg is None:
            return False
        try:
            conn = self._get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_tiktoken;")
            conn.commit()
            return True
        except Exception:
            if self._pg_conn is not None:
                try:
                    self._pg_conn.close()
                except Exception:
                    pass
            self._pg_conn = None
            return False

    def _get_pg_conn(self) -> "psycopg.Connection":
        assert psycopg is not None
        if self._pg_conn is None or self._pg_conn.closed:
            self._pg_conn = psycopg.connect(self.postgres_dsn)
            self._pg_conn.autocommit = True
        return self._pg_conn

    def _count_tokens_postgres(self, text: str, model: str) -> int:
        if psycopg is None:
            raise RuntimeError("PostgreSQL integration is unavailable")
        conn = self._get_pg_conn()
        tiktoken_name = self.get_encoder(model).tokenizer_name
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT tiktoken_count(%s, %s)", (tiktoken_name, text))
                row = cur.fetchone()
                if row and row[0] is not None:
                    return int(row[0])
            except UndefinedFunction:
                cur.execute(
                    "SELECT COUNT(*) FROM tiktoken_encode(%s, %s)",
                    (tiktoken_name, text),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return int(row[0])
                raise
        return 0

    def _get_tokenizer_from_db(self, model: str) -> Optional[str]:
        metadata = get_model_metadata(self.postgres_dsn, model)
        if metadata and metadata.get("tokenizer_model"):
            return str(metadata["tokenizer_model"])
        return None


class BatchAccumulator:
    """Accumulate JSONL request lines respecting token, byte and record limits."""

    def __init__(
        self,
        token_counter: TokenCounter,
        model: str,
        *,
        max_records: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        self.token_counter = token_counter
        self.model = model
        self.token_limit = token_counter.effective_limit
        self.max_records = max_records or token_counter.azure_max_records_per_file
        self.max_bytes = max_bytes or token_counter.azure_max_bytes_per_file
        self.reset()

    def reset(self) -> None:
        self.entries: List[Tuple[str, str, int]] = []
        self.total_tokens = 0
        self.record_count = 0
        self.byte_size = 0

    def compute_tokens(
        self, system_prompt: str, user_prompt: str
    ) -> Tuple[int, int, int]:
        system_tokens = self.token_counter.count_tokens(system_prompt or "", self.model)
        user_tokens = self.token_counter.count_tokens(user_prompt or "", self.model)
        return system_tokens + user_tokens, system_tokens, user_tokens

    @staticmethod
    def compute_byte_size(json_line: str) -> int:
        return len(json_line.encode("utf-8")) + 1  # include newline

    def would_exceed(self, tokens: int, byte_size: int) -> bool:
        if self.record_count == 0:
            return False
        if self.total_tokens + tokens > self.token_limit:
            return True
        if self.byte_size + byte_size > self.max_bytes:
            return True
        if self.record_count + 1 > self.max_records:
            return True
        return False

    def add_entry(
        self, request_id: str, json_line: str, tokens: int, byte_size: int
    ) -> None:
        self.entries.append((request_id, json_line, tokens))
        self.total_tokens += tokens
        self.record_count += 1
        self.byte_size += byte_size

    def drain(self) -> Dict[str, Any]:
        if not self.entries:
            return {}
        metadata = {
            "record_count": self.record_count,
            "total_tokens": self.total_tokens,
            "request_ids": [rid for rid, _, _ in self.entries],
            "lines": [line for _, line, _ in self.entries],
            "byte_size": self.byte_size,
        }
        self.reset()
        return metadata

    def to_jsonl(self) -> str:
        """Return accumulated lines as newline-terminated JSONL text (in-memory)."""
        buffer = StringIO()
        for _, line, _ in self.entries:
            buffer.write(line)
            buffer.write("\n")
        return buffer.getvalue()
