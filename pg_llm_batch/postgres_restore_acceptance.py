# SPDX-License-Identifier: Apache-2.0
"""Inspect a caller-owned PostgreSQL catalog after an isolated restore."""

from __future__ import annotations

from dataclasses import dataclass

from pg_llm_batch.postgres_schema_evidence import inspect_postgres_schema


_REQUIRED_TABLES = (
    "com_config",
    "com_secrets",
    "llm_queues",
    "llm_batches",
    "llm_remote_batch_jobs",
    "llm_batch_file_payloads",
    "llm_batch_files",
    "llm_requests",
    "llm_jsonl_lines",
    "llm_endpoints",
    "llm_endpoint_models",
)
_REQUIRED_INDEXES = (
    "idx_llm_remote_batch_jobs_tenant_status_observed",
    "uq_llm_remote_batch_jobs_tenant_endpoint_id",
)
_CHECKPOINT_TABLE = "llm_result_stream_checkpoints"
_ALLOWED_NAMES = frozenset(_REQUIRED_TABLES + _REQUIRED_INDEXES + (_CHECKPOINT_TABLE,))
_RELATION_KINDS = frozenset({"r", "i"})
_MAX_CATALOG_ROWS = 16
_CATALOG_SQL = """
SELECT c.relname, c.relkind, c.relrowsecurity, c.relforcerowsecurity
FROM pg_catalog.pg_class AS c
INNER JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = current_schema()
  AND c.relkind = ANY(%s)
  AND c.relname = ANY(%s)
""".strip()


class PostgresRestoreAcceptanceError(ValueError):
    """Report a fail-closed isolated restore catalog acceptance violation."""


@dataclass(frozen=True, slots=True)
class PostgresRestoreCatalogEvidence:
    """Represent content-free catalog acceptance for one isolated restore target."""

    required_table_count: int
    required_index_count: int
    lifecycle_rls_enabled: bool
    lifecycle_rls_forced: bool
    checkpoint_store_present: bool
    checkpoint_store_rls_forced: bool
    expected_schema_sha256: str
    expected_schema_size_bytes: int

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable restore-catalog evidence schema."""
        return {
            "required_table_count": self.required_table_count,
            "required_index_count": self.required_index_count,
            "lifecycle_rls_enabled": self.lifecycle_rls_enabled,
            "lifecycle_rls_forced": self.lifecycle_rls_forced,
            "checkpoint_store_present": self.checkpoint_store_present,
            "checkpoint_store_rls_forced": self.checkpoint_store_rls_forced,
            "expected_schema_sha256": self.expected_schema_sha256,
            "expected_schema_size_bytes": self.expected_schema_size_bytes,
        }


def _invalid_catalog() -> None:
    """Reject malformed catalog evidence without reflecting row contents."""
    raise PostgresRestoreAcceptanceError(
        "PostgreSQL restore catalog evidence is invalid"
    )


def _evaluate_catalog_rows(
    rows: object,
) -> PostgresRestoreCatalogEvidence:
    """Validate one finite catalog snapshot against the packaged restore contract."""
    if type(rows) is not list or len(rows) > _MAX_CATALOG_ROWS:
        _invalid_catalog()
    tables: dict[str, tuple[bool, bool]] = {}
    indexes: dict[str, bool] = {}
    for row in rows:
        if type(row) is not tuple or len(row) != 4:
            _invalid_catalog()
        relation_name, relation_kind, row_security, force_row_security = row
        if (
            type(relation_name) is not str
            or relation_name not in _ALLOWED_NAMES
            or type(relation_kind) is not str
            or relation_kind not in _RELATION_KINDS
            or type(row_security) is not bool
            or type(force_row_security) is not bool
        ):
            _invalid_catalog()
        if relation_kind == "r":
            if relation_name in tables:
                _invalid_catalog()
            tables[relation_name] = (row_security, force_row_security)
        else:
            if relation_name in indexes:
                _invalid_catalog()
            indexes[relation_name] = True
    if any(name not in tables for name in _REQUIRED_TABLES):
        raise PostgresRestoreAcceptanceError(
            "PostgreSQL restore catalog is incomplete"
        )
    if any(name not in indexes for name in _REQUIRED_INDEXES):
        raise PostgresRestoreAcceptanceError(
            "PostgreSQL restore catalog is incomplete"
        )
    lifecycle_security = tables["llm_remote_batch_jobs"]
    if not lifecycle_security[0] or not lifecycle_security[1]:
        raise PostgresRestoreAcceptanceError(
            "PostgreSQL restore catalog failed tenant isolation checks"
        )
    checkpoint_present = _CHECKPOINT_TABLE in tables
    checkpoint_security = tables.get(_CHECKPOINT_TABLE, (False, False))
    if checkpoint_present and (not checkpoint_security[0] or not checkpoint_security[1]):
        raise PostgresRestoreAcceptanceError(
            "PostgreSQL restore catalog failed tenant isolation checks"
        )
    schema = inspect_postgres_schema()
    return PostgresRestoreCatalogEvidence(
        required_table_count=len(_REQUIRED_TABLES),
        required_index_count=len(_REQUIRED_INDEXES),
        lifecycle_rls_enabled=lifecycle_security[0],
        lifecycle_rls_forced=lifecycle_security[1],
        checkpoint_store_present=checkpoint_present,
        checkpoint_store_rls_forced=checkpoint_security[1],
        expected_schema_sha256=schema.sha256,
        expected_schema_size_bytes=schema.size_bytes,
    )


def inspect_postgres_restore_catalog(
    connection: object,
) -> PostgresRestoreCatalogEvidence:
    """Prove required package catalog objects on a caller-owned restore target.

    The callable inspects ``pg_class`` through the caller-owned connection. It
    does not execute ``pg_dump`` or ``pg_restore``, open a package-owned
    connection, or claim that a backup artifact is restorable. Missing required
    tables or tenant-status indexes fail closed. Lifecycle row-level security
    must be enabled and forced. A present checkpoint store must also be forced.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                _CATALOG_SQL,
                (("r", "i"), _REQUIRED_TABLES + _REQUIRED_INDEXES + (_CHECKPOINT_TABLE,)),
            )
            rows = cursor.fetchall()
    except Exception:
        raise PostgresRestoreAcceptanceError(
            "PostgreSQL restore catalog could not be inspected"
        ) from None
    return _evaluate_catalog_rows(rows)
