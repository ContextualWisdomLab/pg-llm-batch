# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""pg-llm-batch: standalone + submodule Postgres LLM batch engine.

Public API:
    TokenCounter, BatchAccumulator  -- pg_tiktoken token counting
    PostgresBatchOrchestrator       -- assemble/persist JSONL payloads
    BatchAPIClient                  -- submit/poll/retrieve
    PostgresConfigStore, SecretStore -- KV config + secrets (no os.getenv)
"""

from __future__ import annotations

from .batch_api_client import (
    BatchAPIClient,
    GatewayCredentials,
    config_credentials_provider,
)
from .config import PostgresConfigStore, SecretStore, get_config_store
from .exceptions import (
    ConfigError,
    GatewayError,
    PgLlmBatchError,
    TokenLimitExceededError,
    ValidationError,
)
from .models import BatchRequest, ModelMode
from .orchestrator import BatchPayload, PostgresBatchOrchestrator
from .token_counter import BatchAccumulator, TokenCounter

__version__ = "0.1.0"

__all__ = [
    "BatchAPIClient",
    "GatewayCredentials",
    "config_credentials_provider",
    "PostgresConfigStore",
    "SecretStore",
    "get_config_store",
    "PgLlmBatchError",
    "ConfigError",
    "GatewayError",
    "TokenLimitExceededError",
    "ValidationError",
    "BatchRequest",
    "ModelMode",
    "BatchPayload",
    "PostgresBatchOrchestrator",
    "BatchAccumulator",
    "TokenCounter",
    "__version__",
]
