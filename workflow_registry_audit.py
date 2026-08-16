# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Checkout-local entry point for the packaged workflow registry audit.

Prefer the installed console script ``pg-llm-batch-workflow-audit`` or
``python -m pg_llm_batch.workflow_registry_audit`` after installation. This
module remains so a repository checkout can still run
``python workflow_registry_audit.py`` without changing PYTHONPATH.
"""

from __future__ import annotations

from pg_llm_batch.workflow_registry_audit import (
    GitHubReadClient,
    WorkflowRegistryAuditError,
    audit_live_protected_ref_workflows,
    audit_repository_workflows,
    main,
)

__all__ = [
    "GitHubReadClient",
    "WorkflowRegistryAuditError",
    "audit_live_protected_ref_workflows",
    "audit_repository_workflows",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
