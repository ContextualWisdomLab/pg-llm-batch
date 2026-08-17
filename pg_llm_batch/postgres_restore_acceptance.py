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
LEFT JOIN pg_catalog.pg_index AS idx ON idx.indexrelid = c.oid
LEFT JOIN pg_catalog.pg_class AS indexed_table ON indexed_table.oid = idx.indrelid
WHERE n.nspname = current_schema()
  AND c.relkind = ANY(%s)
  AND c.relname = ANY(%s)
  AND (
      (
          c.relkind = 'r'
          AND (
              c.relname NOT IN (
                  'llm_remote_batch_jobs',
                  'llm_result_stream_checkpoints'
              )
              OR EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_policy AS policy_row
                  WHERE policy_row.polrelid = c.oid
                    AND policy_row.polname::text = CASE c.relname
                        WHEN 'llm_remote_batch_jobs'
                            THEN 'plc_llm_remote_batch_jobs_tenant_scope'
                        WHEN 'llm_result_stream_checkpoints'
                            THEN 'plc_llm_result_stream_checkpoints_tenant_scope'
                        ELSE NULL
                    END
                    AND policy_row.polcmd = '*'
                    AND policy_row.polpermissive IS TRUE
                    AND policy_row.polroles = ARRAY[0::oid]
                    AND replace(
                        regexp_replace(
                            pg_catalog.pg_get_expr(
                                policy_row.polqual,
                                policy_row.polrelid,
                                FALSE
                            ),
                            '[[:space:]]+',
                            '',
                            'g'
                        ),
                        '''pg_llm_batch.tenant_scope''::text',
                        '''pg_llm_batch.tenant_scope'''
                    ) IN (
                        '(tenant_scope=current_setting(''pg_llm_batch.tenant_scope'',true))',
                        'tenant_scope=current_setting(''pg_llm_batch.tenant_scope'',true)'
                    )
                    AND replace(
                        regexp_replace(
                            pg_catalog.pg_get_expr(
                                policy_row.polwithcheck,
                                policy_row.polrelid,
                                FALSE
                            ),
                            '[[:space:]]+',
                            '',
                            'g'
                        ),
                        '''pg_llm_batch.tenant_scope''::text',
                        '''pg_llm_batch.tenant_scope'''
                    ) IN (
                        '(tenant_scope=current_setting(''pg_llm_batch.tenant_scope'',true))',
                        'tenant_scope=current_setting(''pg_llm_batch.tenant_scope'',true)'
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_policy AS extra_policy
                        WHERE extra_policy.polrelid = c.oid
                          AND extra_policy.oid <> policy_row.oid
                    )
              )
          )
      )
      OR (
          c.relkind = 'i'
          AND indexed_table.relname = 'llm_remote_batch_jobs'
          AND indexed_table.relnamespace = n.oid
          AND idx.indisvalid
          AND idx.indisready
          AND idx.indpred IS NULL
          AND idx.indexprs IS NULL
          AND idx.indnkeyatts = 3
          AND idx.indnatts = 3
          AND idx.indoption = '0 0 0'::pg_catalog.int2vector
          AND EXISTS (
              SELECT 1
              FROM pg_catalog.pg_am AS access_method
              WHERE access_method.oid = c.relam
                AND access_method.amname = 'btree'
          )
          AND pg_catalog.pg_get_indexdef(c.oid, 1, TRUE) = 'tenant_scope'
          AND (
              (
                  c.relname = 'idx_llm_remote_batch_jobs_tenant_status_observed'
                  AND NOT idx.indisunique
                  AND pg_catalog.pg_get_indexdef(c.oid, 2, TRUE) = 'batch_status'
                  AND pg_catalog.pg_get_indexdef(c.oid, 3, TRUE) = 'last_observed_at'
              )
              OR (
                  c.relname = 'uq_llm_remote_batch_jobs_tenant_endpoint_id'
                  AND idx.indisunique
                  AND pg_catalog.pg_get_indexdef(c.oid, 2, TRUE) = 'endpoint_alias'
                  AND pg_catalog.pg_get_indexdef(c.oid, 3, TRUE) = 'remote_batch_id'
                  AND EXISTS (
                      SELECT 1
                      FROM pg_catalog.pg_constraint AS constraint_row
                      WHERE constraint_row.conindid = c.oid
                        AND constraint_row.conrelid = indexed_table.oid
                        AND constraint_row.contype = 'u'
                        AND NOT constraint_row.condeferrable
                  )
              )
          )
      )
  )
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

    The callable inspects ``pg_class`` and ``pg_policy`` through the caller-owned
    connection. It does not execute ``pg_dump`` or ``pg_restore``, open a
    package-owned connection, or claim that a backup artifact is restorable.
    Missing required tables or tenant-status indexes fail closed. Lifecycle
    row-level security must be enabled and forced, with exactly the packaged
    permissive ``PUBLIC`` all-command policy whose ``USING`` and ``WITH CHECK``
    predicates bind ``tenant_scope`` to the transaction-local package setting.
    A present checkpoint store must carry the same authenticated policy shape
    and forced RLS. Required lifecycle indexes must belong to that lifecycle
    table and match the packaged key order, uniqueness, validity, readiness,
    btree access method, default key options, and plain-index shape.
    """
    relation_names = list(_REQUIRED_TABLES + _REQUIRED_INDEXES + (_CHECKPOINT_TABLE,))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                _CATALOG_SQL,
                (["r", "i"], relation_names),
            )
            rows = cursor.fetchall()
    except Exception:
        raise PostgresRestoreAcceptanceError(
            "PostgreSQL restore catalog could not be inspected"
        ) from None
    return _evaluate_catalog_rows(rows)
