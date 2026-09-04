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


_EXACT_STRING_REQUEST_FIELDS = frozenset({"user_prompt", "model", "id"})


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

    Generic data-class representations deliberately omit prompt content and the
    caller-selected request identifier. This keeps routine object rendering from
    becoming a package-owned disclosure channel; direct attribute access and
    caller-defined serialization remain explicit caller responsibilities.

    Attributes:
        user_prompt: the user message / embedding input (required).
        model: model id understood by the target gateway.
        system_prompt: optional system message (ignored for embeddings).
        id: stable request identifier used as the JSONL ``custom_id``.
    """

    user_prompt: str = field(repr=False)
    model: str
    system_prompt: Optional[str] = field(default=None, repr=False)
    id: str = field(default_factory=lambda: uuid4().hex, repr=False)

    def __setattr__(self, name: str, value: object) -> None:
        """Keep validated request-field types intact across ordinary assignment."""
        if name in _EXACT_STRING_REQUEST_FIELDS:
            if type(value) is not str:
                raise ValidationError(
                    field=name,
                    value="<redacted>",
                    reason="must be an exact string",
                )
        elif (
            name == "system_prompt"
            and value is not None
            and type(value) is not str
        ):
            raise ValidationError(
                field=name,
                value="<redacted>",
                reason="must be None or an exact string",
            )
        object.__setattr__(self, name, value)
