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

import os
from pathlib import Path
import stat
from typing import Any, Optional
from weakref import WeakKeyDictionary

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
_MAX_MIGRATION_BYTES = 1024 * 1024
_MIGRATION_READ_CHUNK_BYTES = 64 * 1024
_SECURE_MIGRATION_FLAGS_AVAILABLE = all(
    hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_NONBLOCK")
)
_MIGRATION_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_OUTBOX_COLUMNS = (
    "evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256, "
    "authority_ref_sha256, origin_ref_sha256, truth_status, valid_time, "
    "system_time, provenance_ref_sha256, evidence_ref_sha256"
)
_OUTBOX_STORE_BINDINGS: WeakKeyDictionary[object, tuple[str, str, str]] = (
    WeakKeyDictionary()
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
    """Require one exact built-in nonblank database target without ambient fallback."""
    if type(value) is not str or not value.strip():
        raise ConfigError(
            "A Postgres DSN must be provided explicitly for lifecycle outbox persistence"
        )
    return value


def _migration_file_error() -> ConfigError:
    """Return the fixed content-free migration-file authority error."""
    return ConfigError("Lifecycle outbox migration file is unavailable or unsafe")


def _migration_file_identity(status: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Snapshot stable metadata for one retained regular migration file."""
    return (
        status.st_dev,
        status.st_ino,
        stat.S_IFMT(status.st_mode),
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _read_migration_sql(path: Path) -> str:
    """Read one bounded stable UTF-8 migration through retained file authority."""
    if not _SECURE_MIGRATION_FLAGS_AVAILABLE:
        raise _migration_file_error()
    try:
        descriptor = os.open(path, _MIGRATION_FILE_FLAGS)
    except (OSError, ValueError):
        raise _migration_file_error() from None

    failure: BaseException | None = None
    try:
        try:
            before = os.fstat(descriptor)
        except OSError:
            raise _migration_file_error() from None
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > _MAX_MIGRATION_BYTES
        ):
            raise _migration_file_error()

        chunks: list[bytes] = []
        remaining = _MAX_MIGRATION_BYTES + 1
        while remaining > 0:
            try:
                chunk = os.read(
                    descriptor,
                    min(_MIGRATION_READ_CHUNK_BYTES, remaining),
                )
            except OSError:
                raise _migration_file_error() from None
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise _migration_file_error()

        try:
            after = os.fstat(descriptor)
        except OSError:
            raise _migration_file_error() from None
        payload = b"".join(chunks)
        if (
            len(payload) != before.st_size
            or _migration_file_identity(before) != _migration_file_identity(after)
        ):
            raise _migration_file_error()
        try:
            return payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise _migration_file_error() from None
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            os.close(descriptor)
        except OSError:
            if failure is None:
                raise _migration_file_error() from None


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


def _validated_tenant_scope_sha256(value: Any) -> str:
    """Validate the content-free tenant identity bound to one RLS store instance."""
    try:
        probe = validate_context_lifecycle_evidence_seed(
            ContextLifecycleEvidenceSeed(
                evidence_id="tenant-scope-binding",
                event_type="tenant.scope.binding",
                tenant_scope_sha256=value,
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
    except ValueError as exc:
        raise ValidationError(
            field="tenant_scope_sha256",
            value="<redacted>",
            reason="must be an exact lowercase SHA-256 tenant identity",
        ) from exc
    return probe.tenant_scope_sha256


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
    """Snapshot and revalidate one durable row before returning application evidence."""
    if type(row) is tuple:
        snapshot = row
    elif type(row) is list:
        snapshot = tuple(row)
    else:
        raise RuntimeError("context lifecycle outbox row has an invalid shape")
    if len(snapshot) != 11:
        raise RuntimeError("context lifecycle outbox row has an invalid shape")
    return validate_context_lifecycle_evidence_seed(
        ContextLifecycleEvidenceSeed(*snapshot)
    )


def apply_context_lifecycle_outbox_schema(
    postgres_dsn: str,
    migration_path: Optional[str] = None,
) -> None:
    """Apply the idempotent tenant-isolated lifecycle-outbox migration.

    An explicit DSN is mandatory so package code never inherits an unintended libpq
    target. Operators may supply a reviewed regular UTF-8 migration file for
    installation tooling; the package pins its descriptor, enforces a finite byte
    budget, and rejects observed mutation before SQL reaches PostgreSQL. Normal
    callers use the same checks on the package-owned migration.
    """
    dsn = _validated_postgres_dsn(postgres_dsn)
    _require_psycopg()
    path = Path(migration_path) if migration_path else MIGRATION_PATH
    sql = _read_migration_sql(path)
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

    The local RLS tenant and the content-free tenant identity used by future Context
    Fabric evidence are separate representations of the same authorized scope. The
    host therefore supplies both explicitly, and every write/read is checked against
    that binding so a tenant-qualified row cannot claim another tenant identity.

    Validated database and tenant authority lives in a package-owned weak registry,
    not caller-writable instance slots. This keeps later SQL/RLS decisions bound to
    construction-time authority even if a hostile caller invokes ``object.__setattr__``
    or ``object.__delattr__`` directly against the admitted store object. The concrete
    authority-bearing adapter is intentionally non-subclassable so inheritance cannot
    replace those database/RLS properties through virtual dispatch; callers extend the
    boundary by composition behind a port instead.
    """

    __slots__ = ("__weakref__",)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Reject inheritance that could override admitted database or RLS authority."""
        raise TypeError(
            "PostgresContextLifecycleOutboxStore does not support subclassing"
        )

    def __init__(
        self,
        postgres_dsn: str,
        *,
        tenant_scope: str = DEFAULT_TENANT_SCOPE,
        tenant_scope_sha256: str,
    ) -> None:
        """Bind explicit PostgreSQL, RLS-tenant, and external evidence identities."""
        validated_postgres_dsn = _validated_postgres_dsn(postgres_dsn)
        try:
            validated_tenant_scope = validate_tenant_scope(tenant_scope)
        except ValidationError as exc:
            raise ValidationError(
                field="tenant_scope",
                value=tenant_scope,
                reason="must be a supported trusted tenant scope",
            ) from exc
        validated_tenant_scope_sha256 = _validated_tenant_scope_sha256(
            tenant_scope_sha256
        )
        _OUTBOX_STORE_BINDINGS[self] = (
            validated_postgres_dsn,
            validated_tenant_scope,
            validated_tenant_scope_sha256,
        )

    @property
    def postgres_dsn(self) -> str:
        """Return the explicit database target fixed when this store was admitted."""
        return _OUTBOX_STORE_BINDINGS[self][0]

    @property
    def tenant_scope(self) -> str:
        """Return the trusted local RLS tenant fixed when this store was admitted."""
        return _OUTBOX_STORE_BINDINGS[self][1]

    @property
    def tenant_scope_sha256(self) -> str:
        """Return the external content-free tenant identity fixed at admission."""
        return _OUTBOX_STORE_BINDINGS[self][2]

    def _require_tenant_binding(
        self,
        evidence: ContextLifecycleEvidenceSeed,
        *,
        durable_row: bool,
    ) -> ContextLifecycleEvidenceSeed:
        """Reject lifecycle evidence whose tenant identity differs from this store."""
        if evidence.tenant_scope_sha256 == self.tenant_scope_sha256:
            return evidence
        if durable_row:
            raise RuntimeError("context lifecycle outbox tenant scope binding mismatch")
        raise ValidationError(
            field="evidence",
            value="<redacted>",
            reason="tenant scope identity does not match outbox tenant scope binding",
        )

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
        Durable evidence is revalidated and must retain the tenant identity explicitly
        bound to this store before it can return to application code.
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
        if row is None:
            return None
        return self._require_tenant_binding(
            _evidence_from_row(row),
            durable_row=True,
        )

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
        state. The evidence tenant identity must match the explicit tenant binding of
        this store before any transaction-local SQL is executed. The caller owns
        commit and rollback.
        """
        candidate = self._require_tenant_binding(
            _validated_evidence(evidence),
            durable_row=False,
        )
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
