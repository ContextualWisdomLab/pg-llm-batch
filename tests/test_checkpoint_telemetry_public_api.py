# SPDX-License-Identifier: Apache-2.0
"""Public API contract for checkpoint observability."""

from pg_llm_batch import OpenTelemetryCheckpointStore
from pg_llm_batch.checkpoint_telemetry import (
    OpenTelemetryCheckpointStore as ModuleCheckpointStore,
)


def test_checkpoint_telemetry_wrapper_is_exported_from_package_root() -> None:
    """Embedding hosts can import the wrapper from the documented package API."""
    assert OpenTelemetryCheckpointStore is ModuleCheckpointStore
