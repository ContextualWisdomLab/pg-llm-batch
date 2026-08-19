# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Tenant-qualified durable candidate discovery for provider reconciliation."""

from __future__ import annotations

from typing import Any

from .db import (
    _set_transaction_tenant_scope,
    validate_endpoint_alias,
    validate_remote_resource_id,
    validate_tenant_scope,
)
from .exceptions import PgLlmBatchError, ValidationError
from .reconciliation import (
    MAX_RECONCILIATION_CANDIDATES,
    ReconciliationCandidate,
)


class ReconciliationStoreError(PgLlmBatchError):
    """Report a bounded redacted durable reconciliation store failure."""

    def __init__(self) -> None:
        """Initialize the stable content-free store failure category."""
        super().__init__(
            message="Reconciliation candidate store operation failed",
            error_code="RECONCILIATION_STORE_ERROR",
        )


def _validate_candidate_budget(max_candidates: Any) -> int:
    """Return one strict positive bounded durable-candidate query budget."""
    if (
        type(max_candidates) is not int
        or max_candidates < 1
        or max_candidates > MAX_RECONCILIATION_CANDIDATES
    ):
        raise ValidationError(
            field="max_candidates",
            value="<redacted>",
            reason="must be an integer within the supported reconciliation scan budget",
            message="Reconciliation candidate query budget is invalid",
        )
    return max_candidates


def _validate_candidate_tenant(tenant_scope: Any) -> str:
    """Validate exact trusted tenant text without reflecting rejected identity."""
    if type(tenant_scope) is not str:
        raise ValidationError(
            field="tenant_scope",
            value="<redacted>",
            reason="must be a valid host-authorized tenant scope",
            message="Reconciliation tenant scope is invalid",
        ) from None
    try:
        return validate_tenant_scope(tenant_scope)
    except ValidationError:
        raise ValidationError(
            field="tenant_scope",
            value="<redacted>",
            reason="must be a valid host-authorized tenant scope",
            message="Reconciliation tenant scope is invalid",
        ) from None


def _candidate_from_persisted_row(row: Any) -> ReconciliationCandidate:
    """Convert exact database primitives into redaction-safe worker input.

    PostgreSQL row and text evidence must use exact built-in tuple/list and string
    types. Subclasses are rejected before shape, normalization, regex, equality,
    or model construction so caller-controlled row factories cannot execute
    overridden methods or preserve forged identity objects in worker input.
    """
    if type(row) not in (tuple, list) or len(row) != 2:
        raise ValidationError(
            field="reconciliation_candidate",
            value="<redacted>",
            reason="durable candidate row has an invalid shape",
            message="Persisted reconciliation candidate is invalid",
        )
    persisted_endpoint_alias = row[0]
    persisted_remote_batch_id = row[1]
    if (
        type(persisted_endpoint_alias) is not str
        or type(persisted_remote_batch_id) is not str
    ):
        raise ValidationError(
            field="reconciliation_candidate",
            value="<redacted>",
            reason="durable candidate identity has invalid primitive types",
            message="Persisted reconciliation candidate is invalid",
        )
    try:
        endpoint_alias = validate_endpoint_alias(persisted_endpoint_alias)
        if endpoint_alias != persisted_endpoint_alias:
            raise ValidationError(
                field="endpoint_alias",
                value="<redacted>",
                reason="persisted endpoint alias must already be canonical",
            )
        remote_batch_id = validate_remote_resource_id(
            persisted_remote_batch_id,
            "remote_batch_id",
        )
    except ValidationError:
        raise ValidationError(
            field="reconciliation_candidate",
            value="<redacted>",
            reason="durable candidate identity failed validation",
            message="Persisted reconciliation candidate is invalid",
        ) from None
    return ReconciliationCandidate(endpoint_alias, remote_batch_id)


def load_reconciliation_candidates_in_transaction(
    cursor: Any,
    tenant_scope: Any,
    *,
    max_candidates: Any,
) -> tuple[ReconciliationCandidate, ...]:
    """Load a finite oldest-observation candidate page from durable lifecycle state.

    The caller owns the PostgreSQL connection and transaction. This function
    validates the host-authorized tenant and query budget before cursor work,
    binds the tenant through the package's transaction-local RLS setting, and
    reads only the endpoint/batch identities required by the provider worker.

    Selection intentionally includes terminal and non-terminal lifecycle rows.
    Until durable result-application state exists, a stored terminal status does
    not prove that its provider result/error file was applied locally. Ordering
    by the oldest durable observation gives successfully re-polled rows a chance
    to move behind older work after the lifecycle recorder persists a new
    observation; this function does not claim lease, scheduling, or exactly-once
    delivery semantics.

    Args:
        cursor: Caller-owned PostgreSQL cursor in an active transaction. Its
            ``fetchall()`` result must be an exact built-in list no longer than
            ``max_candidates``; each row must be an exact built-in tuple or list.
            Dictionary, named-tuple, subclass, oversized, or other
            behavior-bearing results are rejected at the database boundary.
        tenant_scope: Trusted host-authorized tenant identity.
        max_candidates: Maximum rows to return, from 1 through the package scan
            ceiling.

    Returns:
        A tuple of validated provider reconciliation identities.

    Raises:
        ValidationError: If tenant authority, query budget, or persisted identity
            evidence is invalid.
        ReconciliationStoreError: If tenant binding, candidate querying, row
            retrieval, result-container validation, or row iteration fails at
            the database boundary.
    """
    budget = _validate_candidate_budget(max_candidates)
    normalized_tenant = _validate_candidate_tenant(tenant_scope)
    try:
        _set_transaction_tenant_scope(cursor, normalized_tenant)
        cursor.execute(
            """
            SELECT endpoint_alias, remote_batch_id
            FROM llm_remote_batch_jobs
            WHERE tenant_scope = %s
            ORDER BY last_observed_at ASC,
                     endpoint_alias ASC,
                     remote_batch_id ASC
            LIMIT %s
            """,
            (normalized_tenant, budget),
        )
        rows = cursor.fetchall()
    except Exception:
        raise ReconciliationStoreError() from None

    if type(rows) is not list or len(rows) > budget:
        raise ReconciliationStoreError()

    try:
        return tuple(_candidate_from_persisted_row(row) for row in rows)
    except ValidationError:
        raise
    except Exception:
        raise ReconciliationStoreError() from None
