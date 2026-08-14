# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Bounded scheduler-independent reconciliation through validated Batch API clients."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from typing import Any, Iterable, Mapping, Protocol

from .db import validate_endpoint_alias, validate_remote_resource_id
from .exceptions import GatewayError, ValidationError

MAX_RECONCILIATION_JOBS = 100
MAX_RECONCILIATION_CANDIDATES = 400
_PUBLIC_BATCH_STATUSES = {
    "validating": "validating",
    "failed": "failed",
    "in_progress": "in_progress",
    "finalizing": "finalizing",
    "completed": "completed",
    "expired": "expired",
    "cancelling": "cancelling",
    "cancelled": "cancelled",
}
_ERROR_TYPES = {
    GatewayError: "GatewayError",
    ValidationError: "ValidationError",
}


class ReconciliationClient(Protocol):
    """Minimal validated provider client surface consumed by one reconciliation pass."""

    async def get_batch_status(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Mapping[str, Any]:
        """Return one validated remote batch status snapshot."""
        ...

    async def download_results(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Mapping[str, Any]:
        """Retrieve one terminal batch through the existing bounded client path."""
        ...


@dataclass(frozen=True)
class ReconciliationCandidate:
    """One host-selected provider lifecycle identity eligible for reconciliation."""

    endpoint_alias: str
    remote_batch_id: str


@dataclass(frozen=True)
class ReconciliationOutcome:
    """Payload-free bounded evidence for one attempted reconciliation candidate."""

    outcome: str
    batch_status: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    """Aggregate payload-free evidence from one finite reconciliation pass."""

    processed_count: int
    retrieved_count: int
    failed_count: int
    outcomes: tuple[ReconciliationOutcome, ...]


def _validate_work_budget(max_jobs: Any) -> int:
    """Return one strict positive bounded per-pass provider-work budget."""
    if (
        type(max_jobs) is not int
        or max_jobs < 1
        or max_jobs > MAX_RECONCILIATION_JOBS
    ):
        raise ValidationError(
            field="max_jobs",
            value="<redacted>",
            reason="must be an integer within the supported reconciliation budget",
            message="Reconciliation work budget is invalid",
        )
    return max_jobs


def _validate_candidate(candidate: ReconciliationCandidate) -> ReconciliationCandidate:
    """Validate one selected provider identity without reflecting rejected content."""
    try:
        endpoint_alias = validate_endpoint_alias(candidate.endpoint_alias)
        remote_batch_id = validate_remote_resource_id(
            candidate.remote_batch_id,
            "remote_batch_id",
        )
    except (AttributeError, ValidationError):
        raise ValidationError(
            field="reconciliation_candidate",
            value="<redacted>",
            reason="must contain a valid endpoint alias and remote batch identifier",
            message="Reconciliation candidate identity is invalid",
        ) from None
    return ReconciliationCandidate(endpoint_alias, remote_batch_id)


def _select_candidates(
    candidates: Iterable[ReconciliationCandidate],
    *,
    max_jobs: int,
) -> tuple[ReconciliationCandidate, ...]:
    """Return unique work or fail closed when the bounded candidate scan saturates."""
    selected: list[ReconciliationCandidate] = []
    seen: set[tuple[str, str]] = set()
    candidate_iterator = iter(candidates)
    for candidate in islice(candidate_iterator, MAX_RECONCILIATION_CANDIDATES):
        validated = _validate_candidate(candidate)
        identity = (validated.endpoint_alias, validated.remote_batch_id)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(validated)
        if len(selected) == max_jobs:
            return tuple(selected)

    try:
        next(candidate_iterator)
    except StopIteration:
        return tuple(selected)

    raise ValidationError(
        field="reconciliation_candidates",
        value="<redacted>",
        reason="candidate scan exceeded the bounded reconciliation limit",
        message="Reconciliation candidate scan is saturated",
    )


def _bounded_error_type(error: Exception) -> str:
    """Map one ordinary failure to a finite type vocabulary without dynamic names."""
    return _ERROR_TYPES.get(type(error), "_OTHER")


async def reconcile_batch_candidates(
    client: ReconciliationClient,
    candidates: Iterable[ReconciliationCandidate],
    *,
    max_jobs: int,
) -> ReconciliationReport:
    """Poll and retrieve a finite set of provider jobs without retaining payloads.

    The host owns candidate discovery, scheduling, tenant authorization, and any
    cross-process lease. This primitive validates the selected identities before
    the first provider operation, executes only through the supplied validated
    Batch API client surface, and returns bounded status/error categories rather
    than provider content or dynamic exception diagnostics.
    """
    work_budget = _validate_work_budget(max_jobs)
    selected = _select_candidates(candidates, max_jobs=work_budget)
    outcomes: list[ReconciliationOutcome] = []
    retrieved_count = 0
    failed_count = 0

    for candidate in selected:
        try:
            status = await client.get_batch_status(
                candidate.remote_batch_id,
                candidate.endpoint_alias,
            )
            batch_status = _PUBLIC_BATCH_STATUSES.get(status.get("status"), "_OTHER")
            if status.get("is_complete") is True:
                retrieval = await client.download_results(
                    candidate.remote_batch_id,
                    candidate.endpoint_alias,
                )
                retrieval_succeeded = retrieval.get("success") is True
                outcome = {True: "retrieved", False: "deferred"}[
                    retrieval_succeeded
                ]
                retrieved_count += int(retrieval_succeeded)
            else:
                outcome = "polled"
            outcomes.append(
                ReconciliationOutcome(
                    outcome=outcome,
                    batch_status=batch_status,
                )
            )
        except Exception as error:
            failed_count += 1
            outcomes.append(
                ReconciliationOutcome(
                    outcome="failed",
                    error_type=_bounded_error_type(error),
                )
            )

    return ReconciliationReport(
        processed_count=len(outcomes),
        retrieved_count=retrieved_count,
        failed_count=failed_count,
        outcomes=tuple(outcomes),
    )
