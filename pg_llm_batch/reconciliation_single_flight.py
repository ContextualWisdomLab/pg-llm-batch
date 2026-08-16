# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Tenant-qualified PostgreSQL single-flight authority for reconciliation."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from typing import Any, Iterator

from .db import (
    validate_endpoint_alias,
    validate_remote_resource_id,
    validate_tenant_scope,
)
from .exceptions import PgLlmBatchError, ValidationError
from .reconciliation import ReconciliationCandidate

_LOCK_DOMAIN = b"pg-llm-batch:reconciliation-single-flight:v1"


class ReconciliationSingleFlightError(PgLlmBatchError):
    """Raised when PostgreSQL cannot prove single-flight lock state safely."""

    def __init__(self, phase: str, reason: str) -> None:
        """Create one bounded content-free advisory-lock failure."""
        super().__init__(
            message="Reconciliation single-flight database operation failed",
            error_code="RECONCILIATION_SINGLE_FLIGHT_FAILED",
            details={"phase": phase, "reason": reason},
        )


def _invalid_identity() -> ValidationError:
    """Build the fixed redacted single-flight identity error."""
    return ValidationError(
        field="reconciliation_single_flight_identity",
        value="<redacted>",
        reason=(
            "must contain a valid trusted tenant scope, endpoint alias, and "
            "remote batch identifier"
        ),
        message="Reconciliation single-flight identity is invalid",
    )


def _validated_identity(
    tenant_scope: Any,
    candidate: Any,
) -> tuple[str, str, str]:
    """Return one canonical exact-type lock identity without reflecting bad input.

    Caller-owned identity evidence must use an exact built-in tenant string and
    the exact package-owned candidate dataclass. Candidate members must also be
    exact built-in strings. Subclasses are rejected before attribute methods,
    regex, normalization, hashing, or encoding authority can execute.
    """
    if (
        type(tenant_scope) is not str
        or type(candidate) is not ReconciliationCandidate
    ):
        raise _invalid_identity() from None
    endpoint_value = candidate.endpoint_alias
    remote_value = candidate.remote_batch_id
    if type(endpoint_value) is not str or type(remote_value) is not str:
        raise _invalid_identity() from None
    try:
        tenant = validate_tenant_scope(tenant_scope)
        endpoint_alias = validate_endpoint_alias(endpoint_value)
        remote_batch_id = validate_remote_resource_id(
            remote_value,
            "remote_batch_id",
        )
    except ValidationError:
        raise _invalid_identity() from None
    return tenant, endpoint_alias, remote_batch_id


def _lock_key(tenant_scope: str, endpoint_alias: str, remote_batch_id: str) -> int:
    """Derive one domain-separated signed PostgreSQL advisory-lock key."""
    digest = sha256()
    digest.update(_LOCK_DOMAIN)
    for value in (tenant_scope, endpoint_alias, remote_batch_id):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, byteorder="big"))
        digest.update(encoded)
    return int.from_bytes(digest.digest()[:8], byteorder="big", signed=True)


def _execute_boolean_lock_operation(
    cursor: Any,
    sql: str,
    lock_key: int,
    *,
    phase: str,
) -> bool:
    """Execute one parameterized advisory-lock operation with bounded evidence."""
    try:
        cursor.execute(sql, (lock_key,))
        row = cursor.fetchone()
    except Exception:
        raise ReconciliationSingleFlightError(
            phase,
            "database_operation_failed",
        ) from None

    if (
        type(row) not in (tuple, list)
        or len(row) != 1
        or type(row[0]) is not bool
    ):
        reason = (
            "invalid_database_result"
            if phase == "acquire"
            else "lock_release_not_confirmed"
        )
        raise ReconciliationSingleFlightError(phase, reason) from None
    return row[0]


def _release_single_flight(cursor: Any, lock_key: int) -> None:
    """Release one acquired lock or raise bounded integrity evidence."""
    released = _execute_boolean_lock_operation(
        cursor,
        "SELECT pg_advisory_unlock(%s)",
        lock_key,
        phase="release",
    )
    if not released:
        raise ReconciliationSingleFlightError(
            "release",
            "lock_release_not_confirmed",
        ) from None


@contextmanager
def reconciliation_single_flight(
    cursor: Any,
    tenant_scope: str,
    candidate: ReconciliationCandidate,
) -> Iterator[bool]:
    """Hold a non-blocking cross-process lock for one reconciliation identity.

    The caller owns the PostgreSQL connection and must dedicate that database
    session to at most one concurrent or nested single-flight attempt while this
    context is active. PostgreSQL session advisory locks are re-entrant within a
    session, so sharing the same session between concurrent attempts would not
    provide mutual exclusion. The same session must remain alive for the entire
    context lifetime; process or session loss releases the advisory lock.

    ``True`` means this session acquired authority to reconcile the validated
    tenant/endpoint/remote-batch identity. ``False`` means another database
    session currently holds that authority and the caller should defer. This is
    a transient single-flight primitive, not a durable lease or an exactly-once
    delivery guarantee.

    A release failure remains bounded package evidence. It replaces ordinary
    caller exceptions so sensitive diagnostics are not retained in traceback
    context, while process-control ``BaseException`` signals remain primary and
    chain the bounded release-integrity error as their cause.
    """
    tenant, endpoint_alias, remote_batch_id = _validated_identity(
        tenant_scope,
        candidate,
    )
    lock_key = _lock_key(tenant, endpoint_alias, remote_batch_id)
    acquired = _execute_boolean_lock_operation(
        cursor,
        "SELECT pg_try_advisory_lock(%s)",
        lock_key,
        phase="acquire",
    )
    if not acquired:
        yield False
        return

    caller_error: BaseException | None = None
    try:
        yield True
    except BaseException as error:
        caller_error = error
        raise
    finally:
        try:
            _release_single_flight(cursor, lock_key)
        except ReconciliationSingleFlightError as release_error:
            if caller_error is not None and not isinstance(caller_error, Exception):
                raise caller_error from release_error
            raise
