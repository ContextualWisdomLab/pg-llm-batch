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


class ModelMode(str, Enum):
    """Model invocation mode used when assembling JSONL request lines."""

    CHAT = "chat"
    EMBEDDING = "embedding"


@dataclass
class BatchRequest:
    """A single prompt request to be counted and batched.

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
