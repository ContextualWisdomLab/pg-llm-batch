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
from .postgres_driver_port import PostgresDriverPort

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
    from psycopg.errors import UndefinedFunction  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore
    UndefinedFunction = Exception  # type: ignore


@dataclass(frozen=True)
class _EncoderInfo:
    """Immutable record naming the tiktoken tokenizer used for a model."""

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
        postgres_driver: PostgresDriverPort | None = None,
    ) -> None:
        """Initialize token counting with an optional PostgreSQL migration driver."""
        if not postgres_dsn:
            raise ValidationError(
                field="postgres_dsn",
                value=postgres_dsn,
                reason="A Postgres DSN is required (no os.getenv fallback)",
            )
        self.postgres_dsn = postgres_dsn
        self.config = config
        self._postgres_driver = postgres_driver
        self._pg_conn: Optional[Any] = None
        self._pg_available: bool = False
        self._encoder_cache: Dict[str, _EncoderInfo] = {}

        resolved_buffer = buffer_percentage
        if resolved_buffer is None:
            resolved_buffer = self._resolve_config_value(
                "token_limits", "buffer_percentage", self.DEFAULT_BUFFER_PERCENTAGE
            )
        if type(resolved_buffer) is not int or not 0 <= resolved_buffer <= 50:
            raise ValidationError(
                field="buffer_percentage",
                value=resolved_buffer,
                reason="buffer percentage must be an integer between 0 and 50",
            )
        self.buffer_percentage = resolved_buffer

        max_tokens_per_batch = self._require_positive_limit(
            "max_tokens_per_batch",
            self._resolve_config_value(
                "token_limits", "per_batch", self.DEFAULT_MAX_TOKENS_PER_BATCH
            ),
        )
        self.token_limit = max_tokens_per_batch
        self.effective_limit = (
            max_tokens_per_batch * (100 - self.buffer_percentage) // 100
        )
        self.default_model_limit = self._require_positive_limit(
            "default_model_limit",
            self._resolve_config_value(
                "token_limits", "per_request", self.DEFAULT_MODEL_LIMIT
            ),
        )
        self.azure_max_records_per_file = self._require_positive_limit(
            "azure_max_records_per_file",
            self._resolve_config_value(
                "azure_limits", "max_records_per_file", self.DEFAULT_AZURE_MAX_RECORDS
            ),
        )
        self.azure_max_bytes_per_file = self._require_positive_limit(
            "azure_max_bytes_per_file",
            self._resolve_config_value(
                "azure_limits", "max_bytes_per_file", self.DEFAULT_AZURE_MAX_BYTES
            ),
        )
        self.azure_max_files_per_job = self._require_positive_limit(
            "azure_max_files_per_job",
            self._resolve_config_value(
                "azure_limits", "max_files_per_job", self.DEFAULT_AZURE_MAX_FILES
            ),
        )

        if self._postgres_driver is not None or psycopg is not None:
            self._pg_available = self._ensure_pg_tiktoken()

    @staticmethod
    def _require_positive_limit(field: str, value: Any) -> int:
        """Require a configured resource ceiling to be an exact positive integer."""
        if type(value) is not int or value <= 0:
            raise ValidationError(
                field=field,
                value=value,
                reason="must be a positive integer",
            )
        return value

    def get_tiktoken_name(self, model: str) -> str:
        """Return the tiktoken encoding/model name for ``model``.

        Prefers the DB tokenizer mapping; falls back to the model name, which
        pg_tiktoken maps to a built-in encoding.
        """
        tokenizer_name = self._get_tokenizer_from_db(model)
        if tokenizer_name:
            return tokenizer_name
        logger.debug(  # nosemgrep -- python-logger-credential-disclosure FP: the only logged argument is the model name, not a credential; nothing sensitive is logged.
            "No DB tokenizer mapping for '%s'; using model name with pg_tiktoken "
            "built-in mapping",
            model,
        )
        return model

    def get_encoder(self, model: str) -> _EncoderInfo:
        """Return and cache the tokenizer metadata for a model."""
        cached = self._encoder_cache.get(model)
        if cached:
            return cached
        info = _EncoderInfo(tokenizer_name=self.get_tiktoken_name(model))
        self._encoder_cache[model] = info
        return info

    def count_tokens(self, text: str, model: str) -> int:
        """Count tokens through pg_tiktoken or fail when it is unavailable."""
        if not text:
            return 0
        if self._pg_available:
            try:
                return self._count_tokens_postgres(text, model)
            except Exception as error:  # pragma: no cover - runtime DB variance
                if self._is_undefined_function(error):
                    self._pg_available = False
                    logger.warning("pg_tiktoken extension/functions unavailable")
                else:
                    self.close()
                    logger.debug("PostgreSQL token counting failed")
        raise RuntimeError(
            "Token counting requires pg_tiktoken. Enable the extension and pass a "
            "valid DSN."
        )

    def count_request_tokens(self, request: BatchRequest) -> Tuple[int, int, int]:
        """Return system, user, and total token counts for one request."""
        system_tokens = self.count_tokens(request.system_prompt or "", request.model)
        user_tokens = self.count_tokens(request.user_prompt, request.model)
        return system_tokens, user_tokens, system_tokens + user_tokens

    def count_batch_tokens(self, requests: List[BatchRequest]) -> Dict[str, Any]:
        """Aggregate token statistics and enforce the effective batch limit."""
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
        if current:  # pragma: no branch - every non-empty input appends a request
            batches.append(current)
        return batches

    def close(self) -> None:
        """Close and clear the cached PostgreSQL token-counting connection."""
        conn = self._pg_conn
        self._pg_conn = None
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass

    def _resolve_config_value(self, category: str, key: str, default: Any) -> Any:
        """Read a config value from the KV store, returning the default on any failure."""
        if self.config is not None:
            try:
                value = self.config.get(category, key, default)
                return value if value is not None else default
            except Exception:
                return default
        return default

    def _ensure_pg_tiktoken(self) -> bool:
        """Verify the pre-provisioned pg_tiktoken extension and functions read-only."""
        if self._postgres_driver is None and psycopg is None:
            return False
        try:
            conn = self._get_pg_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                               SELECT 1
                               FROM pg_extension
                               WHERE extname = %s
                           ),
                           to_regprocedure('tiktoken_count(text,text)') IS NOT NULL,
                           to_regprocedure('tiktoken_encode(text,text)') IS NOT NULL
                    """,
                    ("pg_tiktoken",),
                )
                row = cur.fetchone()
            return bool(row and row == (True, True, True))
        except Exception:
            self.close()
            return False

    def _get_pg_conn(self) -> Any:
        """Return a cached autocommit connection through the selected driver boundary."""
        if self._pg_conn is not None:
            if self._postgres_driver is not None:
                if not self._pg_conn.is_closed():
                    return self._pg_conn
            elif not self._pg_conn.closed:
                return self._pg_conn
        if self._postgres_driver is not None:
            self._pg_conn = self._postgres_driver.connect(self.postgres_dsn)
            self._pg_conn.set_autocommit(True)
            return self._pg_conn
        assert psycopg is not None
        self._pg_conn = psycopg.connect(self.postgres_dsn)
        self._pg_conn.autocommit = True
        return self._pg_conn

    def _is_undefined_function(self, error: BaseException) -> bool:
        """Classify undefined-function failures through the selected driver boundary."""
        if self._postgres_driver is not None:
            return self._postgres_driver.is_undefined_function(error)
        return isinstance(error, UndefinedFunction)

    def _count_tokens_postgres(self, text: str, model: str) -> int:
        """Count tokens via pg_tiktoken while preserving driver error classification."""
        if self._postgres_driver is None and psycopg is None:
            raise RuntimeError("PostgreSQL integration is unavailable")
        conn = self._get_pg_conn()
        tiktoken_name = self.get_encoder(model).tokenizer_name
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT tiktoken_count(%s, %s)", (tiktoken_name, text))
                row = cur.fetchone()
                if row and row[0] is not None:
                    return int(row[0])
            except Exception as error:
                if not self._is_undefined_function(error):
                    raise
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
        """Return the tokenizer model recorded in model metadata, or None if unset."""
        if self._postgres_driver is None:
            metadata = get_model_metadata(self.postgres_dsn, model)
        else:
            metadata = get_model_metadata(
                self.postgres_dsn,
                model,
                postgres_driver=self._postgres_driver,
            )
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
        """Initialize an accumulator with validated byte and record ceilings."""
        self.token_counter = token_counter
        self.model = model
        self.token_limit = token_counter.effective_limit
        self.max_records = self._resolve_positive_limit(
            "max_records",
            max_records,
            token_counter.azure_max_records_per_file,
        )
        self.max_bytes = self._resolve_positive_limit(
            "max_bytes",
            max_bytes,
            token_counter.azure_max_bytes_per_file,
        )
        self.reset()

    @staticmethod
    def _resolve_positive_limit(field: str, explicit: Any, configured: Any) -> int:
        """Select an explicit/configured resource ceiling and require a positive integer."""
        selected = configured if explicit is None else explicit
        if type(selected) is not int or selected <= 0:
            raise ValidationError(
                field=field,
                value=selected,
                reason="must be a positive integer",
            )
        return selected

    def reset(self) -> None:
        """Clear all accumulated lines and counters."""
        self.entries: List[Tuple[str, str, int]] = []
        self.total_tokens = 0
        self.record_count = 0
        self.total_bytes = 0
        self._payload = StringIO()

    def can_add(self, jsonl_line: str, tokens: int) -> bool:
        """Return whether an entry would fit every configured resource ceiling."""
        if type(jsonl_line) is not str:
            return False
        if type(tokens) is not int or tokens < 0:
            return False
        line_bytes = len((jsonl_line + "\n").encode("utf-8"))
        if self.record_count + 1 > self.max_records:
            return False
        if self.total_bytes + line_bytes > self.max_bytes:
            return False
        return self.total_tokens + tokens <= self.token_limit

    def add(self, request_id: str, jsonl_line: str, tokens: int) -> bool:
        """Append one validated JSONL line when all resource ceilings permit it."""
        if not self.can_add(jsonl_line, tokens):
            return False
        line_bytes = len((jsonl_line + "\n").encode("utf-8"))
        self.entries.append((request_id, jsonl_line, tokens))
        self._payload.write(jsonl_line)
        self._payload.write("\n")
        self.total_tokens += tokens
        self.record_count += 1
        self.total_bytes += line_bytes
        return True

    def content(self) -> str:
        """Return the canonical newline-terminated JSONL payload."""
        return self._payload.getvalue()

    def is_empty(self) -> bool:
        """Return whether no request has been accumulated."""
        return not self.entries

    def __len__(self) -> int:
        """Return the number of accumulated requests."""
        return self.record_count
