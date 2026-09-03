# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""pg-llm-batch: standalone and embeddable Postgres LLM batch engine.

Public API:
    TokenCounter, BatchAccumulator      -- pg_tiktoken token counting
    PostgresBatchOrchestrator           -- assemble and persist JSONL payloads
    BatchInferencePort                  -- provider-neutral batch lifecycle seam
    ContextLifecycleEvidenceSeed        -- privacy-minimized Context ACL input
    PostgresContextLifecycleOutboxStore -- durable tenant publication intent
    BatchAPIClient                      -- submit, poll, and retrieve
    StreamingBatchAPIClient             -- bounded incremental result records
    BatchResultRecord                   -- immutable streamed result/error record
    BatchResultCheckpoint               -- host-persistable resume evidence
    PostgresBatchResultCheckpointStore  -- durable result checkpoint CAS
    DurableBatchAPIClient               -- standalone durable lifecycle state
    TenantDurableBatchAPIClient         -- tenant-isolated lifecycle state
    PostgresConfigStore, SecretStore    -- database configuration and secrets
"""

from __future__ import annotations

from .batch_api_client import (
    BatchAPIClient,
    GatewayCredentials,
    config_credentials_provider,
)
from .batch_inference_port import BatchInferencePort
from .checkpoint_store import (
    CheckpointConflictError,
    PostgresBatchResultCheckpointStore,
    apply_result_checkpoint_schema,
    validate_checkpoint_consumer_name,
)
from .config import PostgresConfigStore, SecretStore, get_config_store
from .context_lifecycle_evidence import (
    ContextLifecycleEvidenceError,
    ContextLifecycleEvidenceSeed,
    require_context_lifecycle_replay_identity,
    require_context_lifecycle_scope_continuity,
    validate_context_lifecycle_evidence_seed,
)
from .context_lifecycle_outbox import (
    ContextLifecycleOutboxConflictError,
    PostgresContextLifecycleOutboxStore,
    apply_context_lifecycle_outbox_schema,
)
from .db import (
    DEFAULT_TENANT_SCOPE,
    get_remote_batch_state,
    get_tenant_remote_batch_state,
    persist_tenant_remote_batch_state,
    validate_tenant_scope,
)
from .durable_client import DurableBatchAPIClient, TenantDurableBatchAPIClient
from .exceptions import (
    ConfigError,
    GatewayError,
    PgLlmBatchError,
    TokenLimitExceededError,
    ValidationError,
)
from .models import BatchRequest, ModelMode
from .orchestrator import BatchPayload, PostgresBatchOrchestrator
from .result_streaming import (
    BatchResultCheckpoint,
    BatchResultRecord,
    CheckpointedBatchResultRecord,
    StreamingBatchAPIClient,
)
from .token_counter import BatchAccumulator, TokenCounter

__version__ = "0.1.0"

__all__ = [
    "BatchInferencePort",
    "ContextLifecycleEvidenceError",
    "ContextLifecycleEvidenceSeed",
    "validate_context_lifecycle_evidence_seed",
    "require_context_lifecycle_replay_identity",
    "require_context_lifecycle_scope_continuity",
    "ContextLifecycleOutboxConflictError",
    "PostgresContextLifecycleOutboxStore",
    "apply_context_lifecycle_outbox_schema",
    "BatchAPIClient",
    "StreamingBatchAPIClient",
    "BatchResultRecord",
    "BatchResultCheckpoint",
    "CheckpointedBatchResultRecord",
    "CheckpointConflictError",
    "PostgresBatchResultCheckpointStore",
    "apply_result_checkpoint_schema",
    "validate_checkpoint_consumer_name",
    "DurableBatchAPIClient",
    "TenantDurableBatchAPIClient",
    "DEFAULT_TENANT_SCOPE",
    "validate_tenant_scope",
    "persist_tenant_remote_batch_state",
    "get_tenant_remote_batch_state",
    "get_remote_batch_state",
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
