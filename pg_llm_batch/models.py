# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Lightweight data models for pg_llm_batch.

The upstream project used pydantic; the extracted core only needs a plain
dataclass, so this package stays dependency-light (stdlib + psycopg + aiohttp).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import uuid4

from .exceptions import ValidationError


class ModelMode(str, Enum):
    """Model invocation mode used when assembling JSONL request lines."""

    CHAT = "chat"
    EMBEDDING = "embedding"


@dataclass
class BatchRequest:
    """A single prompt request to be counted and batched.

    Runtime values are deliberately type-strict: ``user_prompt``, ``model``,
    and ``id`` must already be exact strings, while ``system_prompt`` must be
    ``None`` or an exact string. The model does not stringify caller objects or
    reinterpret false-valued non-strings as empty prompts. Empty strings remain
    accepted for compatibility; content-policy validation belongs to the host
    or provider contract rather than this lightweight request record.

    Attributes:
        user_prompt: the user message / embedding input (required).
        model: model id understood by the target gateway.
        system_prompt: optional system message (ignored for embeddings).
        id: stable request identifier used as the JSONL ``custom_id``.
    """

    user_prompt: str
    model: str
    system_prompt: Optional[str] = None
    id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        """Reject non-string values before they reach counting or gateway seams."""
        if type(self.user_prompt) is not str:
            raise ValidationError(
                field="user_prompt",
                value="<redacted>",
                reason="must be an exact string",
            )
        if type(self.model) is not str:
            raise ValidationError(
                field="model",
                value="<redacted>",
                reason="must be an exact string",
            )
        if self.system_prompt is not None and type(self.system_prompt) is not str:
            raise ValidationError(
                field="system_prompt",
                value="<redacted>",
                reason="must be None or an exact string",
            )
        if type(self.id) is not str:
            raise ValidationError(
                field="id",
                value="<redacted>",
                reason="must be an exact string",
            )
