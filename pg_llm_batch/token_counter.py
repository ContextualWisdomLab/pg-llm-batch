# SPDX-License-Identifier: Apache-2.0
"""Token counting utilities backed by PostgreSQL ``pg_tiktoken``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Iterable, Mapping, Optional

from .exceptions import TokenCountingError, ValidationError

try:  # pragma: no cover - optional dependency import itself is environment-specific
    import psycopg
except ImportError:  # pragma: no cover - exercised through behavior tests
    psycopg = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from .models import BatchRequest


@dataclass(frozen=True)
class _EncoderInfo:
    """Cached tokenizer metadata loaded from PostgreSQL."""

    model_name: str
    encoding_name: str
    max_context_tokens: int


class TokenCounter:
    """Count request tokens and enforce configured batch resource ceilings."""

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
        """Initialize PostgreSQL token counting and configured batch limits."""
        if not isinstance(postgres_dsn, str):
            raise ValidationError(
                field="postgres_dsn",
                value="<invalid>",
                reason="must be a non-empty string",
            )
        postgres_dsn_snapshot = str.__str__(postgres_dsn)
        if not postgres_dsn_snapshot.strip():
            raise ValidationError(
                field="postgres_dsn",
                value="<invalid>",
                reason="must be a non-empty string",
            )
        self.postgres_dsn = postgres_dsn_snapshot
        self.config = config
        self._pg_conn: Optional["psycopg.Connection"] = None
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
                "batch_limits", "max_tokens_per_batch", self.DEFAULT_MAX_TOKENS_PER_BATCH
            ),
        )
        max_records = self._require_positive_limit(
            "azure_max_records",
            self._resolve_config_value(
                "batch_limits", "azure_max_records", self.DEFAULT_AZURE_MAX_RECORDS
            ),
        )
        max_bytes = self._require_positive_limit(
            "azure_max_bytes",
            self._resolve_config_value(
                "batch_limits", "azure_max_bytes", self.DEFAULT_AZURE_MAX_BYTES
            ),
        )
        max_files = self._require_positive_limit(
            "azure_max_files",
            self._resolve_config_value(
                "batch_limits", "azure_max_files", self.DEFAULT_AZURE_MAX_FILES
            ),
        )
        self.max_tokens_per_batch = max_tokens_per_batch
        self.azure_max_records = max_records
        self.azure_max_bytes = max_bytes
        self.azure_max_files = max_files
        self._ensure_pg_tiktoken()

    def _resolve_config_value(self, category: str, key: str, default: Any) -> Any:
        """Resolve one configured value while preserving standalone defaults."""
        if self.config is None:
            return default
        try:
            return self.config.get(category, key, default)
        except Exception as exc:
            raise ValidationError(
                field=f"{category}.{key}",
                value="<unavailable>",
                reason="configuration authority could not be read",
            ) from exc

    @staticmethod
    def _require_positive_limit(field: str, value: Any) -> int:
        """Validate a positive integer resource ceiling without truthiness coercion."""
        if type(value) is not int or value <= 0:
            raise ValidationError(
                field=field,
                value=value,
                reason="resource ceiling must be a positive integer",
            )
        return value

    def _ensure_pg_tiktoken(self) -> None:
        """Detect PostgreSQL/``pg_tiktoken`` availability without making it mandatory."""
        if psycopg is None:
            return
        try:
            self._pg_conn = psycopg.connect(self.postgres_dsn)
            with self._pg_conn.cursor() as cursor:
                cursor.execute("SELECT to_regprocedure('tiktoken_count(text,text)')")
                row = cursor.fetchone()
            self._pg_available = bool(row and row[0])
        except Exception:
            if self._pg_conn is not None:
                try:
                    self._pg_conn.close()
                except Exception:
                    pass
            self._pg_conn = None
            self._pg_available = False

    def close(self) -> None:
        """Close the PostgreSQL connection used for token counting."""
        if self._pg_conn is None:
            return
        try:
            self._pg_conn.close()
        finally:
            self._pg_conn = None
            self._pg_available = False

    def __enter__(self) -> "TokenCounter":
        """Return this counter as a synchronous context manager."""
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Release database resources when leaving a context manager."""
        self.close()

    def _encoder_info(self, model_name: str) -> _EncoderInfo:
        """Load tokenizer metadata from PostgreSQL, caching successful lookups."""
        cached = self._encoder_cache.get(model_name)
        if cached is not None:
            return cached
        encoding_name = model_name
        model_limit = self.DEFAULT_MODEL_LIMIT
        if self._pg_available and self._pg_conn is not None:
            try:
                with self._pg_conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT model_name, encoding_name, max_context_tokens
                        FROM llm_model_tokenizer_metadata
                        WHERE model_name = %s
                        """,
                        (model_name,),
                    )
                    row = cursor.fetchone()
                if row is not None:
                    encoding_name = str(row[1])
                    model_limit = int(row[2])
            except Exception:
                pass
        info = _EncoderInfo(
            model_name=model_name,
            encoding_name=encoding_name,
            max_context_tokens=model_limit,
        )
        self._encoder_cache[model_name] = info
        return info

    def count_text(self, text: str, model_name: str) -> int:
        """Count text tokens using PostgreSQL when available or deterministic fallback."""
        if not isinstance(text, str):
            raise ValidationError(
                field="text", value=text, reason="text must be a string"
            )
        info = self._encoder_info(model_name)
        if self._pg_available and self._pg_conn is not None:
            try:
                with self._pg_conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT tiktoken_count(%s, %s)", (info.encoding_name, text)
                    )
                    row = cursor.fetchone()
                if row is not None:
                    return int(row[0])
            except Exception as exc:
                raise TokenCountingError(
                    reason="PostgreSQL token counting failed",
                    model_name=model_name,
                ) from exc
        if not text:
            return 0
        return max(1, (len(text) + 3) // 4)

    def count_messages(self, messages: Iterable[Mapping[str, Any]], model_name: str) -> int:
        """Count chat-message tokens with deterministic structural overhead."""
        total = 0
        for message in messages:
            total += 4
            for key, value in message.items():
                total += self.count_text(str(value), model_name)
                if key == "name":
                    total -= 1
        return total + 2

    def count_request(self, request: "BatchRequest") -> int:
        """Count tokens in a batch request payload."""
        payload = request.payload
        model_name = request.model_name
        if "messages" in payload:
            messages = payload["messages"]
            if not isinstance(messages, list):
                raise ValidationError(
                    field="messages", value=messages, reason="messages must be a list"
                )
            return self.count_messages(messages, model_name)
        if "prompt" in payload:
            return self.count_text(str(payload["prompt"]), model_name)
        return self.count_text(json.dumps(payload, sort_keys=True), model_name)

    def model_limit(self, model_name: str) -> int:
        """Return the effective token ceiling for one model."""
        info = self._encoder_info(model_name)
        buffered_limit = int(
            info.max_context_tokens * (100 - self.buffer_percentage) / 100
        )
        return max(1, buffered_limit)

    def validate_request(self, request: "BatchRequest") -> int:
        """Count and validate one request against its effective model ceiling."""
        token_count = self.count_request(request)
        limit = self.model_limit(request.model_name)
        if token_count > limit:
            raise ValidationError(
                field="token_count",
                value=token_count,
                reason=f"request exceeds effective model limit {limit}",
            )
        return token_count

    def validate_batch(
        self, requests: Iterable["BatchRequest"]
    ) -> tuple[int, int, int]:
        """Validate aggregate token, record, and byte ceilings for one submission."""
        records = list(requests)
        record_count = len(records)
        if record_count > self.azure_max_records:
            raise ValidationError(
                field="record_count",
                value=record_count,
                reason=f"batch exceeds record limit {self.azure_max_records}",
            )
        total_tokens = 0
        total_bytes = 0
        for request in records:
            total_tokens += self.validate_request(request)
            total_bytes += len(
                json.dumps(request.payload, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
        if total_tokens > self.max_tokens_per_batch:
            raise ValidationError(
                field="total_tokens",
                value=total_tokens,
                reason=f"batch exceeds token limit {self.max_tokens_per_batch}",
            )
        if total_bytes > self.azure_max_bytes:
            raise ValidationError(
                field="total_bytes",
                value=total_bytes,
                reason=f"batch exceeds byte limit {self.azure_max_bytes}",
            )
        return total_tokens, record_count, total_bytes

    def partition_requests(
        self, requests: Iterable["BatchRequest"]
    ) -> list[list["BatchRequest"]]:
        """Partition requests into deterministic provider-neutral internal batches."""
        records = list(requests)
        if not records:
            return []
        partitions: list[list["BatchRequest"]] = []
        current: list["BatchRequest"] = []
        current_tokens = 0
        current_bytes = 0
        for request in records:
            request_tokens = self.validate_request(request)
            request_bytes = len(
                json.dumps(request.payload, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            exceeds_count = len(current) >= self.MAX_REQUESTS_PER_INTERNAL_BATCH
            exceeds_tokens = current_tokens + request_tokens > self.max_tokens_per_batch
            exceeds_bytes = current_bytes + request_bytes > self.azure_max_bytes
            if current and (exceeds_count or exceeds_tokens or exceeds_bytes):
                partitions.append(current)
                current = []
                current_tokens = 0
                current_bytes = 0
            current.append(request)
            current_tokens += request_tokens
            current_bytes += request_bytes
        if current:
            partitions.append(current)
        return partitions
