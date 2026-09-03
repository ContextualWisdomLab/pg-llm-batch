# SPDX-License-Identifier: Apache-2.0
"""Persist privacy-minimized lifecycle evidence in a tenant-isolated outbox.

The outbox is a pg-llm-batch-owned durability boundary, not a Context Fabric wire
implementation. It stores only validated ``ContextLifecycleEvidenceSeed`` values so
local domain state and publication intent can commit in one PostgreSQL transaction.
A later adapter may translate a row only through an independently verified released
Context Graph contract. No prompt, response, provider body, credential, routing state,
or arbitrary metadata is accepted by this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .context_lifecycle_evidence import (
    ContextLifecycleEvidenceSeed,
    validate_context_lifecycle_evidence_seed,
)
from .db import (
    DEFAULT_TENANT_SCOPE,
    _require_psycopg,
    _set_transaction_tenant_scope,
    psycopg,
    validate_tenant_scope,
)
from .exceptions import ConfigError, PgLlmBatchError, ValidationError

MIGRATION_PATH = Path(__file__).with_name("migrations") / "0008_context_lifecycle_outbox.sql"
ROLLBACK_PATH = (
    Path(__file__).with_name("migrations")
    / "rollback"
    / "0008_context_lifecycle_outbox.sql"
)
_OUTBOX_COLUMNS = (
    "evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256, "
    "authority_ref_sha256, origin_ref_sha256, truth_status, valid_time, "
    "system_time, provenance_ref_sha256, evidence_ref_sha256"
)


class ContextLifecycleOutboxConflictError(PgLlmBatchError):
    """Report a durable event-identity conflict without exposing evidence content."""

    def __init__(self, evidence_id: str, reason: str) -> None:
        """Describe one bounded outbox conflict for operator reconciliation."""
        super().__init__(
            message="Context lifecycle outbox write conflicted with durable state",
            error_code="CONTEXT_LIFECYCLE_OUTBOX_CONFLICT",
            details={"evidence_id": evidence_id, "reason": reason},
        )
        self.evidence_id = evidence_id
        self.reason = reason


def _validated_postgres_dsn(value: Any) -> str:
    """Require an explicit nonblank database target without ambient fallback."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "A Postgres DSN must be provided explicitly for lifecycle outbox persistence"
        )
    return value


def _validated_evidence(value: Any) -> ContextLifecycleEvidenceSeed:
    """Require and snapshot one package-owned privacy-minimized evidence value."""
    try:
        return validate_context_lifecycle_evidence_seed(value)
    except ValueError as exc:
        raise ValidationError(
            field="evidence",
            value="<redacted>",
            reason="must be valid ContextLifecycleEvidenceSeed",
        ) from exc


def _evidence_values(evidence: ContextLifecycleEvidenceSeed) -> tuple[Any, ...]:
    """Return the stable SQL value order for one validated evidence snapshot."""
    return (
        evidence.evidence_id,
        evidence.event_type,
        evidence.tenant_scope_sha256,
        evidence.subject_ref_sha256,
        evidence.authority_ref_sha256,
        evidence.origin_ref_sha256,
        evidence.truth_status,
        evidence.valid_time,
        evidence.system_time,
        evidence.provenance_ref_sha256,
        evidence.evidence_ref_sha256,
    )


def _evidence_from_row(row: Any) -> ContextLifecycleEvidenceSeed:
    """Revalidate one durable row before returning it to the application boundary."""
    if not isinstance(row, (tuple, list)) or len(row) != 11:
        raise RuntimeError("context lifecycle outbox row has an invalid shape")
    return validate_context_lifecycle_evidence_seed(ContextLifecycleEvidenceSeed(*row))


def apply_context_lifecycle_outbox_schema(
    postgres_dsn: str,
    migration_path: Optional[str] = None,
) -> None:
    """Apply the idempotent tenant-isolated lifecycle-outbox migration.

    An explicit DSN is mandatory so package code never inherits an unintended libpq
    target. Operators may supply a reviewed migration path for installation tooling;
    normal callers use the package-owned migration.
    """
    dsn = _validated_postgres_dsn(postgres_dsn)
    _require_psycopg()
    path = Path(migration_path) if migration_path else MIGRATION_PATH
    sql = path.read_text(encoding="utf-8")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


class PostgresContextLifecycleOutboxStore:
    """Persist content-free lifecycle publication intent with tenant RLS isolation.

    ``enqueue_in_transaction`` is the critical outbox boundary: a caller may persist
    its local domain transition and the publication seed through the same PostgreSQL
    transaction. The store does not contact Context Fabric and therefore remains safe
    when no upstream immutable release exists. Reusing an ``evidence_id`` is accepted
    only for an exact replay; semantic drift fails closed instead of overwriting the
    durable intent.
    """

    def __init__(
        self,
        postgres_dsn: str,
        *,
        tenant_scope: str = DEFAULT_TENANT_SCOPE,
    ) -> None:
        """Bind one explicit PostgreSQL target and trusted local tenant scope."""
        self.postgres_dsn = _validated_postgres_dsn(postgres_dsn)
        try:
            self.tenant_scope = validate_tenant_scope(tenant_scope)
        except ValidationError as exc:
            raise ValidationError(
                field="tenant_scope",
                value=tenant_scope,
                reason="must be a supported trusted tenant scope",
            ) from exc

    def load(self, evidence_id: str) -> Optional[ContextLifecycleEvidenceSeed]:
        """Load one durable event through a package-owned read transaction."""
        _require_psycopg()
        with psycopg.connect(self.postgres_dsn) as conn:
            with conn.cursor() as cur:
                return self.load_in_transaction(cur, evidence_id)

    def load_in_transaction(
        self,
        cursor: Any,
        evidence_id: str,
        *,
        for_update: bool = False,
    ) -> Optional[ContextLifecycleEvidenceSeed]:
        """Load one tenant-qualified event through a caller-owned transaction.

        The identifier is validated through the same evidence contract before SQL is
        executed, avoiding a second, subtly different event-id grammar. ``for_update``
        is reserved for compare-and-swap writers and keeps row locking explicit.
        """
        probe = _validated_evidence(
            ContextLifecycleEvidenceSeed(
                evidence_id=evidence_id,
                event_type="probe",
                tenant_scope_sha256="0" * 64,
                subject_ref_sha256="0" * 64,
                authority_ref_sha256="0" * 64,
                origin_ref_sha256="0" * 64,
                truth_status="observed",
                valid_time="1970-01-01T00:00:00Z",
                system_time="1970-01-01T00:00:00Z",
                provenance_ref_sha256="0" * 64,
                evidence_ref_sha256="0" * 64,
            )
        )
        _set_transaction_tenant_scope(cursor, self.tenant_scope)
        locking = " FOR UPDATE" if for_update else ""
        cursor.execute(
            f"SELECT {_OUTBOX_COLUMNS} FROM llm_context_lifecycle_outbox "
            "WHERE tenant_scope = %s AND evidence_id = %s" + locking,
            (self.tenant_scope, probe.evidence_id),
        )
        row = cursor.fetchone()
        return None if row is None else _evidence_from_row(row)

    def enqueue(
        self,
        evidence: ContextLifecycleEvidenceSeed,
    ) -> ContextLifecycleEvidenceSeed:
        """Persist one event in a package-owned transaction and commit it."""
        _require_psycopg()
        with psycopg.connect(self.postgres_dsn) as conn:
            with conn.cursor() as cur:
                stored = self.enqueue_in_transaction(cur, evidence)
            conn.commit()
        return stored

    def enqueue_in_transaction(
        self,
        cursor: Any,
        evidence: ContextLifecycleEvidenceSeed,
    ) -> ContextLifecycleEvidenceSeed:
        """Insert publication intent atomically with caller-owned local domain work.

        Exact duplicate retries are idempotent. If the same tenant/event identity is
        already bound to different content-free lifecycle evidence, the write fails
        with ``ContextLifecycleOutboxConflictError`` and does not replace durable
        state. The caller owns commit and rollback.
        """
        candidate = _validated_evidence(evidence)
        existing = self.load_in_transaction(
            cursor,
            candidate.evidence_id,
            for_update=True,
        )
        if existing is not None:
            if existing == candidate:
                return existing
            raise ContextLifecycleOutboxConflictError(
                candidate.evidence_id,
                "conflicting_replay",
            )

        cursor.execute(
            "INSERT INTO llm_context_lifecycle_outbox ("
            "tenant_scope, evidence_id, event_type, tenant_scope_sha256, "
            "subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, "
            "truth_status, valid_time, system_time, provenance_ref_sha256, "
            "evidence_ref_sha256) VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_scope, evidence_id) DO NOTHING "
            "RETURNING evidence_id",
            (self.tenant_scope, *_evidence_values(candidate)),
        )
        if cursor.fetchone() is not None:
            return candidate

        concurrent = self.load_in_transaction(
            cursor,
            candidate.evidence_id,
            for_update=True,
        )
        if concurrent is None:
            raise RuntimeError("context lifecycle outbox insert conflict row disappeared")
        if concurrent == candidate:
            return concurrent
        raise ContextLifecycleOutboxConflictError(
            candidate.evidence_id,
            "initial_event_race",
        )
