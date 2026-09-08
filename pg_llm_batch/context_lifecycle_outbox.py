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

import hashlib
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
    psycopg,
    validate_tenant_scope,
)
from .exceptions import ConfigError, PgLlmBatchError, ValidationError

MIGRATION_PATH = Path(__file__).with_name("migrations") / "0008_context_lifecycle_outbox.sql"
_ROW_ADMISSION_AUTHORITY_MIGRATION_PATH = (
    Path(__file__).with_name("migrations")
    / "0009_context_lifecycle_outbox_row_admission_authority.sql"
)
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


def _event_identity_lock_key(tenant_scope: str, evidence_id: str) -> int:
    """Derive one stable signed 64-bit advisory-lock key for a tenant/event identity."""
    material = tenant_scope.encode("utf-8") + b"\x00" + evidence_id.encode("utf-8")
    return int.from_bytes(
        hashlib.sha256(material).digest()[:8],
        byteorder="big",
        signed=True,
    )


def _maintain_privilege_sql(role_expression: str) -> str:
    """Build a PostgreSQL-16-safe probe for the table privilege added in PostgreSQL 17."""
    return (
        "CASE WHEN pg_catalog.current_setting('server_version_num')::pg_catalog.int4 "
        "OPERATOR(pg_catalog.>=) 170000 THEN pg_catalog.has_table_privilege("
        f"{role_expression}, admitted_relation.oid, 'MAINTAIN') ELSE false END"
    )


def _privileged_outbox_view_sql(role_expression: str) -> str:
    """Probe reachable views, copies, inheritance, and opaque foreign-data authority."""
    return (
        "EXISTS ("
        "WITH RECURSIVE foreign_inheritance_ancestor(relation_oid) AS ("
        "SELECT foreign_inheritance_leaf.oid "
        "FROM pg_catalog.pg_class AS foreign_inheritance_leaf "
        "WHERE foreign_inheritance_leaf.relkind::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'f' "
        "UNION "
        "SELECT foreign_inheritance_edge.inhparent "
        "FROM foreign_inheritance_ancestor "
        "JOIN pg_catalog.pg_inherits AS foreign_inheritance_edge "
        "ON foreign_inheritance_edge.inhrelid OPERATOR(pg_catalog.=) "
        "foreign_inheritance_ancestor.relation_oid"
        "), reachable_relation(relation_oid, caller_oid) AS ("
        "SELECT exposed_relation.oid, "
        f"{role_expression} "
        "FROM pg_catalog.pg_class AS exposed_relation "
        "JOIN pg_catalog.pg_namespace AS exposed_relation_schema "
        "ON exposed_relation_schema.oid OPERATOR(pg_catalog.=) "
        "exposed_relation.relnamespace "
        "WHERE (exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'v' "
        "OR exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'm' "
        "OR exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'f' "
        "OR ((exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'r' "
        "OR exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'p') "
        "AND EXISTS ("
        "SELECT 1 FROM foreign_inheritance_ancestor "
        "WHERE foreign_inheritance_ancestor.relation_oid "
        "OPERATOR(pg_catalog.=) exposed_relation.oid))) "
        "AND exposed_relation_schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' "
        "AND exposed_relation_schema.nspname OPERATOR(pg_catalog.<>) "
        "'information_schema' "
        "AND pg_catalog.has_schema_privilege("
        f"{role_expression}, exposed_relation_schema.oid, 'USAGE') "
        "AND pg_catalog.has_table_privilege("
        f"{role_expression}, exposed_relation.oid, 'SELECT') "
        "UNION "
        "SELECT nested_relation.oid, reachable_relation.caller_oid "
        "FROM reachable_relation "
        "JOIN pg_catalog.pg_class AS current_view "
        "ON current_view.oid OPERATOR(pg_catalog.=) reachable_relation.relation_oid "
        "JOIN pg_catalog.pg_rewrite AS current_view_rule "
        "ON current_view_rule.ev_class OPERATOR(pg_catalog.=) current_view.oid "
        "JOIN pg_catalog.pg_depend AS current_view_dependency "
        "ON current_view_dependency.classid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_rewrite'::pg_catalog.regclass "
        "AND current_view_dependency.objid OPERATOR(pg_catalog.=) current_view_rule.oid "
        "AND current_view_dependency.refclassid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_class'::pg_catalog.regclass "
        "JOIN pg_catalog.pg_class AS nested_relation "
        "ON nested_relation.oid OPERATOR(pg_catalog.=) current_view_dependency.refobjid "
        "JOIN pg_catalog.pg_namespace AS nested_relation_schema "
        "ON nested_relation_schema.oid OPERATOR(pg_catalog.=) nested_relation.relnamespace "
        "WHERE current_view.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'v' "
        "AND (nested_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'v' "
        "OR nested_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'm' "
        "OR nested_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'f' "
        "OR ((nested_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'r' "
        "OR nested_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'p') "
        "AND EXISTS ("
        "SELECT 1 FROM foreign_inheritance_ancestor "
        "WHERE foreign_inheritance_ancestor.relation_oid "
        "OPERATOR(pg_catalog.=) nested_relation.oid))) "
        "AND nested_relation_schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' "
        "AND nested_relation_schema.nspname OPERATOR(pg_catalog.<>) 'information_schema' "
        "AND pg_catalog.has_table_privilege("
        "CASE WHEN COALESCE("
        "current_view.reloptions OPERATOR(pg_catalog.@>) "
        "ARRAY['security_invoker=true']::pg_catalog.text[], false) "
        "THEN reachable_relation.caller_oid ELSE current_view.relowner END, "
        "nested_relation.oid, 'SELECT')"
        "), materialized_source(materialized_oid, source_oid) AS ("
        "SELECT reachable_materialized.oid, materialized_dependency.refobjid "
        "FROM reachable_relation "
        "JOIN pg_catalog.pg_class AS reachable_materialized "
        "ON reachable_materialized.oid OPERATOR(pg_catalog.=) "
        "reachable_relation.relation_oid "
        "JOIN pg_catalog.pg_rewrite AS materialized_rule "
        "ON materialized_rule.ev_class OPERATOR(pg_catalog.=) reachable_materialized.oid "
        "JOIN pg_catalog.pg_depend AS materialized_dependency "
        "ON materialized_dependency.classid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_rewrite'::pg_catalog.regclass "
        "AND materialized_dependency.objid OPERATOR(pg_catalog.=) materialized_rule.oid "
        "AND materialized_dependency.refclassid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_class'::pg_catalog.regclass "
        "WHERE reachable_materialized.relkind::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'm' "
        "AND materialized_dependency.refobjid OPERATOR(pg_catalog.<>) "
        "reachable_materialized.oid "
        "UNION "
        "SELECT materialized_source.materialized_oid, nested_source_dependency.refobjid "
        "FROM materialized_source "
        "JOIN pg_catalog.pg_class AS materialized_source_relation "
        "ON materialized_source_relation.oid OPERATOR(pg_catalog.=) "
        "materialized_source.source_oid "
        "JOIN pg_catalog.pg_rewrite AS materialized_source_rule "
        "ON materialized_source_rule.ev_class OPERATOR(pg_catalog.=) "
        "materialized_source_relation.oid "
        "JOIN pg_catalog.pg_depend AS nested_source_dependency "
        "ON nested_source_dependency.classid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_rewrite'::pg_catalog.regclass "
        "AND nested_source_dependency.objid OPERATOR(pg_catalog.=) "
        "materialized_source_rule.oid "
        "AND nested_source_dependency.refclassid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_class'::pg_catalog.regclass "
        "WHERE (materialized_source_relation.relkind::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'v' "
        "OR materialized_source_relation.relkind::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'm') "
        "AND nested_source_dependency.refobjid OPERATOR(pg_catalog.<>) "
        "materialized_source_relation.oid"
        ") "
        "SELECT 1 FROM reachable_relation "
        "JOIN pg_catalog.pg_class AS exposed_relation "
        "ON exposed_relation.oid OPERATOR(pg_catalog.=) reachable_relation.relation_oid "
        "JOIN pg_catalog.pg_roles AS exposed_relation_owner "
        "ON exposed_relation_owner.oid OPERATOR(pg_catalog.=) exposed_relation.relowner "
        "WHERE ((exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'v' "
        "AND NOT COALESCE("
        "exposed_relation.reloptions OPERATOR(pg_catalog.@>) "
        "ARRAY['security_invoker=true']::pg_catalog.text[], false) "
        "AND EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_rewrite AS exposed_view_rule "
        "JOIN pg_catalog.pg_depend AS exposed_view_dependency "
        "ON exposed_view_dependency.classid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_rewrite'::pg_catalog.regclass "
        "AND exposed_view_dependency.objid OPERATOR(pg_catalog.=) exposed_view_rule.oid "
        "AND exposed_view_dependency.refclassid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_class'::pg_catalog.regclass "
        "WHERE exposed_view_rule.ev_class OPERATOR(pg_catalog.=) exposed_relation.oid "
        "AND exposed_view_dependency.refobjid OPERATOR(pg_catalog.=) admitted_relation.oid"
        ") "
        "AND pg_catalog.has_any_column_privilege("
        "exposed_relation_owner.oid, admitted_relation.oid, 'SELECT') "
        "AND (exposed_relation_owner.rolsuper OR exposed_relation_owner.rolbypassrls)) "
        "OR (exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'm' "
        "AND EXISTS ("
        "SELECT 1 FROM materialized_source "
        "WHERE materialized_source.materialized_oid OPERATOR(pg_catalog.=) "
        "exposed_relation.oid "
        "AND (materialized_source.source_oid OPERATOR(pg_catalog.=) "
        "admitted_relation.oid "
        "OR EXISTS ("
        "SELECT 1 FROM foreign_inheritance_ancestor "
        "WHERE foreign_inheritance_ancestor.relation_oid OPERATOR(pg_catalog.=) "
        "materialized_source.source_oid))"
        ")) "
        "OR EXISTS ("
        "SELECT 1 FROM foreign_inheritance_ancestor "
        "WHERE foreign_inheritance_ancestor.relation_oid OPERATOR(pg_catalog.=) "
        "exposed_relation.oid))"
        ")"
    )


def _unsafe_outbox_index_sql() -> str:
    """Probe live index programs and noncanonical uniqueness authority on the outbox."""
    return (
        "EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_index AS live_outbox_index "
        "JOIN pg_catalog.pg_class AS live_outbox_index_relation "
        "ON live_outbox_index_relation.oid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indexrelid "
        "WHERE live_outbox_index.indrelid OPERATOR(pg_catalog.=) admitted_relation.oid "
        "AND (live_outbox_index.indexprs IS NOT NULL "
        "OR live_outbox_index.indpred IS NOT NULL "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.generate_series("
        "0, live_outbox_index.indnkeyatts - 1"
        ") AS live_outbox_key_position(position) "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_opclass AS live_outbox_opclass "
        "JOIN pg_catalog.pg_attribute AS live_outbox_attribute "
        "ON live_outbox_attribute.attrelid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indrelid "
        "AND live_outbox_attribute.attnum OPERATOR(pg_catalog.=) "
        "live_outbox_index.indkey[live_outbox_key_position.position] "
        "AND live_outbox_attribute.attnum OPERATOR(pg_catalog.>) 0 "
        "AND NOT live_outbox_attribute.attisdropped "
        "WHERE live_outbox_opclass.oid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indclass[live_outbox_key_position.position] "
        "AND live_outbox_opclass.opcmethod OPERATOR(pg_catalog.=) "
        "live_outbox_index_relation.relam "
        "AND live_outbox_opclass.opcnamespace OPERATOR(pg_catalog.=) "
        "'pg_catalog'::pg_catalog.regnamespace "
        "AND live_outbox_opclass.opcdefault "
        "AND live_outbox_opclass.opcintype OPERATOR(pg_catalog.=) "
        "live_outbox_attribute.atttypid)) "
        "OR (live_outbox_index.indisunique AND NOT EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_constraint AS live_outbox_constraint "
        "WHERE live_outbox_constraint.conrelid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indrelid "
        "AND live_outbox_constraint.conindid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indexrelid "
        "AND (((live_outbox_constraint.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'p') "
        "AND live_outbox_constraint.convalidated "
        "AND NOT live_outbox_constraint.condeferrable "
        "AND NOT live_outbox_constraint.condeferred "
        "AND live_outbox_constraint.conkey OPERATOR(pg_catalog.=) ARRAY[("
        "SELECT live_outbox_pk_attribute.attnum::pg_catalog.int2 "
        "FROM pg_catalog.pg_attribute AS live_outbox_pk_attribute "
        "WHERE live_outbox_pk_attribute.attrelid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indrelid "
        "AND live_outbox_pk_attribute.attname OPERATOR(pg_catalog.=) "
        "'context_outbox_uuid' "
        "AND live_outbox_pk_attribute.attnum OPERATOR(pg_catalog.>) 0 "
        "AND NOT live_outbox_pk_attribute.attisdropped)]) "
        "OR ((live_outbox_constraint.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'u') "
        "AND live_outbox_constraint.conname OPERATOR(pg_catalog.=) "
        "'uq_llm_context_lifecycle_outbox_tenant_evidence' "
        "AND live_outbox_constraint.convalidated "
        "AND NOT live_outbox_constraint.condeferrable "
        "AND NOT live_outbox_constraint.condeferred "
        "AND live_outbox_constraint.conkey OPERATOR(pg_catalog.=) ARRAY[("
        "SELECT live_outbox_tenant_attribute.attnum::pg_catalog.int2 "
        "FROM pg_catalog.pg_attribute AS live_outbox_tenant_attribute "
        "WHERE live_outbox_tenant_attribute.attrelid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indrelid "
        "AND live_outbox_tenant_attribute.attname OPERATOR(pg_catalog.=) 'tenant_scope' "
        "AND live_outbox_tenant_attribute.attnum OPERATOR(pg_catalog.>) 0 "
        "AND NOT live_outbox_tenant_attribute.attisdropped), ("
        "SELECT live_outbox_evidence_attribute.attnum::pg_catalog.int2 "
        "FROM pg_catalog.pg_attribute AS live_outbox_evidence_attribute "
        "WHERE live_outbox_evidence_attribute.attrelid OPERATOR(pg_catalog.=) "
        "live_outbox_index.indrelid "
        "AND live_outbox_evidence_attribute.attname OPERATOR(pg_catalog.=) 'evidence_id' "
        "AND live_outbox_evidence_attribute.attnum OPERATOR(pg_catalog.>) 0 "
        "AND NOT live_outbox_evidence_attribute.attisdropped)]))))))"
    )


def _unsafe_outbox_constraint_sql() -> str:
    """Probe constraint-set and executable dependency authority after migration."""
    return (
        "((SELECT pg_catalog.count(*) "
        "FROM pg_catalog.pg_constraint AS live_outbox_constraint_authority "
        "WHERE live_outbox_constraint_authority.conrelid OPERATOR(pg_catalog.=) "
        "admitted_relation.oid "
        "AND (live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'c' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'f' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'p' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'u' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'x'))"
        ") OPERATOR(pg_catalog.<>) 5 "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_constraint AS live_outbox_constraint_authority "
        "WHERE live_outbox_constraint_authority.conrelid OPERATOR(pg_catalog.=) "
        "admitted_relation.oid "
        "AND (live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'c' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'f' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'p' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'u' "
        "OR live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'x') "
        "AND NOT ("
        "((live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'p') "
        "AND live_outbox_constraint_authority.convalidated "
        "AND NOT live_outbox_constraint_authority.condeferrable "
        "AND NOT live_outbox_constraint_authority.condeferred "
        "AND live_outbox_constraint_authority.conkey OPERATOR(pg_catalog.=) ARRAY[("
        "SELECT live_outbox_constraint_pk_attribute.attnum::pg_catalog.int2 "
        "FROM pg_catalog.pg_attribute AS live_outbox_constraint_pk_attribute "
        "WHERE live_outbox_constraint_pk_attribute.attrelid OPERATOR(pg_catalog.=) "
        "admitted_relation.oid "
        "AND live_outbox_constraint_pk_attribute.attname OPERATOR(pg_catalog.=) "
        "'context_outbox_uuid' "
        "AND live_outbox_constraint_pk_attribute.attnum OPERATOR(pg_catalog.>) 0 "
        "AND NOT live_outbox_constraint_pk_attribute.attisdropped)]) "
        "OR ((live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'u') "
        "AND live_outbox_constraint_authority.conname OPERATOR(pg_catalog.=) "
        "'uq_llm_context_lifecycle_outbox_tenant_evidence' "
        "AND live_outbox_constraint_authority.convalidated "
        "AND NOT live_outbox_constraint_authority.condeferrable "
        "AND NOT live_outbox_constraint_authority.condeferred "
        "AND live_outbox_constraint_authority.conkey OPERATOR(pg_catalog.=) ARRAY[("
        "SELECT live_outbox_constraint_tenant_attribute.attnum::pg_catalog.int2 "
        "FROM pg_catalog.pg_attribute AS live_outbox_constraint_tenant_attribute "
        "WHERE live_outbox_constraint_tenant_attribute.attrelid OPERATOR(pg_catalog.=) "
        "admitted_relation.oid "
        "AND live_outbox_constraint_tenant_attribute.attname OPERATOR(pg_catalog.=) "
        "'tenant_scope' "
        "AND live_outbox_constraint_tenant_attribute.attnum OPERATOR(pg_catalog.>) 0 "
        "AND NOT live_outbox_constraint_tenant_attribute.attisdropped), ("
        "SELECT live_outbox_constraint_evidence_attribute.attnum::pg_catalog.int2 "
        "FROM pg_catalog.pg_attribute AS live_outbox_constraint_evidence_attribute "
        "WHERE live_outbox_constraint_evidence_attribute.attrelid OPERATOR(pg_catalog.=) "
        "admitted_relation.oid "
        "AND live_outbox_constraint_evidence_attribute.attname OPERATOR(pg_catalog.=) "
        "'evidence_id' "
        "AND live_outbox_constraint_evidence_attribute.attnum OPERATOR(pg_catalog.>) 0 "
        "AND NOT live_outbox_constraint_evidence_attribute.attisdropped)]) "
        "OR ((live_outbox_constraint_authority.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'c') "
        "AND live_outbox_constraint_authority.convalidated "
        "AND NOT live_outbox_constraint_authority.connoinherit "
        "AND (((live_outbox_constraint_authority.conname OPERATOR(pg_catalog.=) "
        "'ck_llm_context_lifecycle_outbox_payload_canonical_v1') "
        "AND pg_catalog.regexp_replace("
        "pg_catalog.pg_get_expr(live_outbox_constraint_authority.conbin, "
        "live_outbox_constraint_authority.conrelid, false), "
        "E'\\n[[:space:]]*', ' ', 'g') OPERATOR(pg_catalog.=) "
        "$pg_llm_batch_payload$((tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text) AND (evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text) AND (event_type ~ '^[a-z][a-z0-9._:-]{0,127}$'::text) AND (tenant_scope_sha256 ~ '^[0-9a-f]{64}$'::text) AND (subject_ref_sha256 ~ '^[0-9a-f]{64}$'::text) AND (authority_ref_sha256 ~ '^[0-9a-f]{64}$'::text) AND (origin_ref_sha256 ~ '^[0-9a-f]{64}$'::text) AND (truth_status = ANY (ARRAY['authoritative'::text, 'observed'::text, 'inferred'::text, 'proposed'::text, 'superseded'::text, 'rejected'::text])) AND (provenance_ref_sha256 ~ '^[0-9a-f]{64}$'::text) AND (evidence_ref_sha256 ~ '^[0-9a-f]{64}$'::text))$pg_llm_batch_payload$) "
        "OR ((live_outbox_constraint_authority.conname OPERATOR(pg_catalog.=) "
        "'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1') "
        "AND pg_catalog.regexp_replace("
        "pg_catalog.pg_get_expr(live_outbox_constraint_authority.conbin, "
        "live_outbox_constraint_authority.conrelid, false), "
        "E'\\n[[:space:]]*', ' ', 'g') OPERATOR(pg_catalog.=) "
        "$pg_llm_batch_valid_time$((valid_time ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}([.]\\d{6})?Z$'::text) AND ((valid_time)::timestamp with time zone IS NOT NULL) AND (valid_time !~ '[.]000000Z$'::text) AND (valid_time = CASE WHEN (valid_time ~ '[.]'::text) THEN to_char(((valid_time)::timestamp with time zone AT TIME ZONE 'UTC'::text), 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'::text) ELSE to_char(((valid_time)::timestamp with time zone AT TIME ZONE 'UTC'::text), 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'::text) END))$pg_llm_batch_valid_time$) "
        "OR ((live_outbox_constraint_authority.conname OPERATOR(pg_catalog.=) "
        "'ck_llm_context_lifecycle_outbox_system_time_canonical_v1') "
        "AND pg_catalog.regexp_replace("
        "pg_catalog.pg_get_expr(live_outbox_constraint_authority.conbin, "
        "live_outbox_constraint_authority.conrelid, false), "
        "E'\\n[[:space:]]*', ' ', 'g') OPERATOR(pg_catalog.=) "
        "$pg_llm_batch_system_time$((system_time ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}([.]\\d{6})?Z$'::text) AND ((system_time)::timestamp with time zone IS NOT NULL) AND (system_time !~ '[.]000000Z$'::text) AND (system_time = CASE WHEN (system_time ~ '[.]'::text) THEN to_char(((system_time)::timestamp with time zone AT TIME ZONE 'UTC'::text), 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'::text) ELSE to_char(((system_time)::timestamp with time zone AT TIME ZONE 'UTC'::text), 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'::text) END))$pg_llm_batch_system_time$)))"
        ") "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_constraint AS live_outbox_check_dependency_owner "
        "JOIN pg_catalog.pg_depend AS live_outbox_check_dependency "
        "ON live_outbox_check_dependency.classid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_constraint'::pg_catalog.regclass "
        "AND live_outbox_check_dependency.objid OPERATOR(pg_catalog.=) "
        "live_outbox_check_dependency_owner.oid "
        "AND live_outbox_check_dependency.objsubid OPERATOR(pg_catalog.=) 0 "
        "WHERE live_outbox_check_dependency_owner.conrelid OPERATOR(pg_catalog.=) "
        "admitted_relation.oid "
        "AND live_outbox_check_dependency_owner.contype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'c' "
        "AND live_outbox_check_dependency.refobjsubid OPERATOR(pg_catalog.=) 0 "
        "AND live_outbox_check_dependency.deptype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'n'"
        "))"
    )


def _unsafe_outbox_default_sql() -> str:
    """Probe live omitted-column defaults that can execute after migration admission."""
    return (
        "((SELECT pg_catalog.count(*) "
        "FROM pg_catalog.pg_attrdef AS live_outbox_default "
        "WHERE live_outbox_default.adrelid OPERATOR(pg_catalog.=) admitted_relation.oid"
        ") OPERATOR(pg_catalog.<>) 3 "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_attrdef AS live_outbox_default "
        "JOIN pg_catalog.pg_attribute AS live_outbox_default_attribute "
        "ON live_outbox_default_attribute.attrelid OPERATOR(pg_catalog.=) "
        "live_outbox_default.adrelid "
        "AND live_outbox_default_attribute.attnum OPERATOR(pg_catalog.=) "
        "live_outbox_default.adnum "
        "WHERE live_outbox_default.adrelid OPERATOR(pg_catalog.=) admitted_relation.oid "
        "AND NOT ("
        "(live_outbox_default_attribute.attname OPERATOR(pg_catalog.=) 'tenant_scope' "
        "AND pg_catalog.pg_get_expr(live_outbox_default.adbin, "
        "live_outbox_default.adrelid, false) OPERATOR(pg_catalog.=) "
        "'''standalone''::text') "
        "OR (live_outbox_default_attribute.attname OPERATOR(pg_catalog.=) "
        "'context_outbox_uuid' "
        "AND pg_catalog.pg_get_expr(live_outbox_default.adbin, "
        "live_outbox_default.adrelid, false) OPERATOR(pg_catalog.=) "
        "'gen_random_uuid()') "
        "OR (live_outbox_default_attribute.attname OPERATOR(pg_catalog.=) 'created_at' "
        "AND pg_catalog.pg_get_expr(live_outbox_default.adbin, "
        "live_outbox_default.adrelid, false) OPERATOR(pg_catalog.=) 'now()')"
        ")) "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_attrdef AS live_outbox_default "
        "JOIN pg_catalog.pg_depend AS live_outbox_default_dependency "
        "ON live_outbox_default_dependency.classid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_attrdef'::pg_catalog.regclass "
        "AND live_outbox_default_dependency.objid OPERATOR(pg_catalog.=) "
        "live_outbox_default.oid "
        "AND live_outbox_default_dependency.objsubid OPERATOR(pg_catalog.=) 0 "
        "WHERE live_outbox_default.adrelid OPERATOR(pg_catalog.=) admitted_relation.oid "
        "AND live_outbox_default_dependency.deptype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'n'"
        "))"
    )


def _require_rls_application_role(cursor: Any) -> None:
    """Reject unsafe runtime roles or drifted canonical RLS policy authority."""
    maintain_selectable = _maintain_privilege_sql("selectable_role.oid")
    maintain_delegated_dml = _maintain_privilege_sql("delegated_dml_role.oid")
    maintain_definer = _maintain_privilege_sql("definer_role.oid")
    maintain_definer_delegated = _maintain_privilege_sql(
        "definer_delegated_role_details.oid"
    )
    privileged_delegated_dml_relation = _privileged_outbox_view_sql(
        "delegated_dml_role.oid"
    )
    privileged_definer_relation = _privileged_outbox_view_sql("definer_role.oid")
    privileged_definer_delegated_relation = _privileged_outbox_view_sql(
        "definer_delegated_role_details.oid"
    )
    privileged_outbox_view = _privileged_outbox_view_sql("selectable_role.oid")
    unsafe_outbox_index = _unsafe_outbox_index_sql()
    unsafe_outbox_constraint = _unsafe_outbox_constraint_sql()
    unsafe_outbox_default = _unsafe_outbox_default_sql()
    cursor.execute(
        "SELECT admitted_role.rolsuper "
        "OR NOT admitted_relation.relrowsecurity "
        "OR NOT admitted_relation.relforcerowsecurity "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_trigger AS live_outbox_trigger "
        "WHERE live_outbox_trigger.tgrelid OPERATOR(pg_catalog.=) admitted_relation.oid "
        "AND NOT live_outbox_trigger.tgisinternal"
        ") "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_rewrite AS live_outbox_rule "
        "WHERE live_outbox_rule.ev_class OPERATOR(pg_catalog.=) admitted_relation.oid"
        ") "
        "OR "
        f"{unsafe_outbox_index} "
        "OR "
        f"{unsafe_outbox_constraint} "
        "OR "
        f"{unsafe_outbox_default} "
        "OR ("
        "SELECT pg_catalog.count(*) FROM pg_catalog.pg_policy AS outbox_policy "
        "WHERE outbox_policy.polrelid OPERATOR(pg_catalog.=) admitted_relation.oid"
        ") OPERATOR(pg_catalog.<>) 1 "
        "OR NOT EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_policy AS outbox_policy "
        "WHERE outbox_policy.polrelid OPERATOR(pg_catalog.=) admitted_relation.oid "
        "AND outbox_policy.polname OPERATOR(pg_catalog.=) "
        "'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2' "
        "AND outbox_policy.polcmd OPERATOR(pg_catalog.=) '*' "
        "AND outbox_policy.polpermissive "
        "AND outbox_policy.polroles OPERATOR(pg_catalog.=) "
        "ARRAY[0::pg_catalog.oid] "
        "AND pg_catalog.pg_get_expr(outbox_policy.polqual, "
        "outbox_policy.polrelid, false) OPERATOR(pg_catalog.=) "
        "'(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))' "
        "AND pg_catalog.pg_get_expr(outbox_policy.polwithcheck, "
        "outbox_policy.polrelid, false) OPERATOR(pg_catalog.=) "
        "'(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))' "
        "AND NOT EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_depend AS unexpected_policy_dependency "
        "WHERE unexpected_policy_dependency.classid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_policy'::pg_catalog.regclass "
        "AND unexpected_policy_dependency.objid OPERATOR(pg_catalog.=) "
        "outbox_policy.oid "
        "AND unexpected_policy_dependency.objsubid OPERATOR(pg_catalog.=) 0 "
        "AND unexpected_policy_dependency.refobjsubid OPERATOR(pg_catalog.=) 0 "
        "AND unexpected_policy_dependency.deptype::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'n' "
        "AND ((unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_proc'::pg_catalog.regclass "
        "AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>) "
        "'pg_catalog.current_setting(pg_catalog.text,pg_catalog.bool)'::pg_catalog.regprocedure) "
        "OR (unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=) "
        "'pg_catalog.pg_operator'::pg_catalog.regclass "
        "AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>) "
        "'pg_catalog.=(pg_catalog.text,pg_catalog.text)'::pg_catalog.regoperator))"
        ")) "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_roles AS selectable_role "
        "WHERE ("
        "selectable_role.rolname OPERATOR(pg_catalog.=) CURRENT_USER "
        "OR selectable_role.rolname OPERATOR(pg_catalog.=) SESSION_USER "
        "OR pg_catalog.pg_has_role("
        "SESSION_USER, selectable_role.oid, 'SET') "
        "OR pg_catalog.pg_has_role("
        "SESSION_USER, selectable_role.oid, 'MEMBER WITH ADMIN OPTION')"
        ") AND ("
        "selectable_role.oid OPERATOR(pg_catalog.=) admitted_relation.relowner "
        "OR pg_catalog.pg_has_role("
        "selectable_role.oid, admitted_relation.relowner, 'USAGE') "
        "OR pg_catalog.pg_has_role("
        "selectable_role.oid, admitted_relation.relowner, 'SET') "
        "OR pg_catalog.pg_has_role("
        "selectable_role.oid, admitted_relation.relowner, "
        "'MEMBER WITH ADMIN OPTION') "
        "OR (pg_catalog.pg_has_role("
        "SESSION_USER, selectable_role.oid, 'MEMBER WITH ADMIN OPTION') AND "
        "(pg_catalog.has_any_column_privilege("
        "selectable_role.oid, admitted_relation.oid, 'SELECT') OR "
        "pg_catalog.has_any_column_privilege("
        "selectable_role.oid, admitted_relation.oid, 'INSERT') OR "
        f"{maintain_selectable})) "
        "OR EXISTS ("
        "WITH RECURSIVE delegated_role(role_oid, admin_seen) AS ("
        "SELECT selectable_role.oid, pg_catalog.pg_has_role("
        "SESSION_USER, selectable_role.oid, 'MEMBER WITH ADMIN OPTION') "
        "UNION "
        "SELECT delegated_membership.roleid, "
        "delegated_role.admin_seen OR delegated_membership.admin_option "
        "FROM delegated_role "
        "JOIN pg_catalog.pg_auth_members AS delegated_membership "
        "ON delegated_membership.member OPERATOR(pg_catalog.=) delegated_role.role_oid "
        "WHERE delegated_membership.set_option OR delegated_membership.admin_option"
        ") "
        "SELECT 1 FROM delegated_role "
        "JOIN pg_catalog.pg_roles AS delegated_dml_role "
        "ON delegated_dml_role.oid OPERATOR(pg_catalog.=) delegated_role.role_oid "
        "WHERE delegated_dml_role.oid OPERATOR(pg_catalog.<>) selectable_role.oid "
        "AND delegated_role.admin_seen AND ("
        "delegated_dml_role.rolsuper "
        "OR delegated_dml_role.rolcreatedb "
        "OR delegated_dml_role.rolcreaterole "
        "OR delegated_dml_role.rolreplication "
        "OR delegated_dml_role.rolbypassrls "
        "OR delegated_dml_role.oid OPERATOR(pg_catalog.=) admitted_relation.relowner "
        "OR pg_catalog.pg_has_role("
        "delegated_dml_role.oid, admitted_relation.relowner, 'USAGE') "
        "OR pg_catalog.pg_has_role("
        "delegated_dml_role.oid, admitted_relation.relowner, 'SET') "
        "OR pg_catalog.pg_has_role("
        "delegated_dml_role.oid, admitted_relation.relowner, "
        "'MEMBER WITH ADMIN OPTION') "
        "OR pg_catalog.has_any_column_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'SELECT') "
        "OR pg_catalog.has_any_column_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'INSERT') "
        "OR pg_catalog.has_any_column_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'SELECT WITH GRANT OPTION') "
        "OR pg_catalog.has_any_column_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'INSERT WITH GRANT OPTION') "
        "OR "
        f"{maintain_delegated_dml} "
        "OR pg_catalog.has_table_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'TRUNCATE') "
        "OR pg_catalog.has_table_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'DELETE') "
        "OR pg_catalog.has_any_column_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'UPDATE') "
        "OR pg_catalog.has_any_column_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'REFERENCES') "
        "OR pg_catalog.has_table_privilege("
        "delegated_dml_role.oid, admitted_relation.oid, 'TRIGGER') "
        "OR "
        f"{privileged_delegated_dml_relation})) "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_proc AS executable_invoker_scope_override "
        "JOIN pg_catalog.pg_namespace AS invoker_scope_schema "
        "ON invoker_scope_schema.oid OPERATOR(pg_catalog.=) "
        "executable_invoker_scope_override.pronamespace "
        "WHERE NOT executable_invoker_scope_override.prosecdef "
        "AND invoker_scope_schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' "
        "AND invoker_scope_schema.nspname OPERATOR(pg_catalog.<>) 'information_schema' "
        "AND pg_catalog.has_schema_privilege("
        "selectable_role.oid, invoker_scope_schema.oid, 'USAGE') "
        "AND pg_catalog.has_function_privilege("
        "selectable_role.oid, executable_invoker_scope_override.oid, 'EXECUTE') "
        "AND EXISTS ("
        "SELECT 1 FROM pg_catalog.unnest(COALESCE("
        "executable_invoker_scope_override.proconfig, ARRAY[]::pg_catalog.text[]"
        ")) AS invoker_scope_setting(setting) "
        "WHERE pg_catalog.split_part(invoker_scope_setting.setting, '=', 1) "
        "OPERATOR(pg_catalog.=) 'pg_llm_batch.tenant_scope'"
        ")) "
        "OR EXISTS ("
        "WITH RECURSIVE executable_definer_owner(role_oid, routine_oid) AS ("
        "SELECT executable_definer.proowner, executable_definer.oid "
        "FROM pg_catalog.pg_proc AS executable_definer "
        "JOIN pg_catalog.pg_namespace AS definer_schema "
        "ON definer_schema.oid OPERATOR(pg_catalog.=) executable_definer.pronamespace "
        "WHERE executable_definer.prosecdef "
        "AND definer_schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' "
        "AND definer_schema.nspname OPERATOR(pg_catalog.<>) 'information_schema' "
        "AND pg_catalog.has_schema_privilege("
        "selectable_role.oid, definer_schema.oid, 'USAGE') "
        "AND pg_catalog.has_function_privilege("
        "selectable_role.oid, executable_definer.oid, 'EXECUTE') "
        "UNION "
        "SELECT nested_executable_definer.proowner, nested_executable_definer.oid "
        "FROM executable_definer_owner "
        "CROSS JOIN pg_catalog.pg_proc AS nested_executable_definer "
        "JOIN pg_catalog.pg_namespace AS nested_definer_schema "
        "ON nested_definer_schema.oid OPERATOR(pg_catalog.=) "
        "nested_executable_definer.pronamespace "
        "WHERE nested_executable_definer.prosecdef "
        "AND nested_definer_schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' "
        "AND nested_definer_schema.nspname OPERATOR(pg_catalog.<>) 'information_schema' "
        "AND pg_catalog.has_schema_privilege("
        "executable_definer_owner.role_oid, nested_definer_schema.oid, 'USAGE') "
        "AND pg_catalog.has_function_privilege("
        "executable_definer_owner.role_oid, nested_executable_definer.oid, 'EXECUTE')"
        ") "
        "SELECT 1 FROM executable_definer_owner "
        "JOIN pg_catalog.pg_proc AS admitted_definer "
        "ON admitted_definer.oid OPERATOR(pg_catalog.=) "
        "executable_definer_owner.routine_oid "
        "JOIN pg_catalog.pg_roles AS definer_role "
        "ON definer_role.oid OPERATOR(pg_catalog.=) executable_definer_owner.role_oid "
        "WHERE (NOT COALESCE("
        "admitted_definer.proconfig OPERATOR(pg_catalog.@>) "
        "ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[], false) "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.unnest(COALESCE("
        "admitted_definer.proconfig, ARRAY[]::pg_catalog.text[]"
        ")) AS definer_setting(setting) "
        "WHERE pg_catalog.split_part(definer_setting.setting, '=', 1) "
        "OPERATOR(pg_catalog.=) 'pg_llm_batch.tenant_scope'"
        ") "
        "OR EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_proc AS definer_invoker_scope_override "
        "JOIN pg_catalog.pg_namespace AS definer_invoker_scope_schema "
        "ON definer_invoker_scope_schema.oid OPERATOR(pg_catalog.=) "
        "definer_invoker_scope_override.pronamespace "
        "WHERE NOT definer_invoker_scope_override.prosecdef "
        "AND definer_invoker_scope_schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' "
        "AND definer_invoker_scope_schema.nspname OPERATOR(pg_catalog.<>) "
        "'information_schema' "
        "AND pg_catalog.has_schema_privilege("
        "definer_role.oid, definer_invoker_scope_schema.oid, 'USAGE') "
        "AND pg_catalog.has_function_privilege("
        "definer_role.oid, definer_invoker_scope_override.oid, 'EXECUTE') "
        "AND EXISTS ("
        "SELECT 1 FROM pg_catalog.unnest(COALESCE("
        "definer_invoker_scope_override.proconfig, ARRAY[]::pg_catalog.text[]"
        ")) AS definer_invoker_scope_setting(setting) "
        "WHERE pg_catalog.split_part(definer_invoker_scope_setting.setting, '=', 1) "
        "OPERATOR(pg_catalog.=) 'pg_llm_batch.tenant_scope'"
        ")) "
        "OR definer_role.rolsuper "
        "OR definer_role.rolcreaterole "
        "OR definer_role.rolreplication "
        "OR definer_role.rolbypassrls "
        "OR definer_role.oid OPERATOR(pg_catalog.=) admitted_relation.relowner "
        "OR pg_catalog.pg_has_role("
        "definer_role.oid, admitted_relation.relowner, 'USAGE') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_role.oid, admitted_relation.oid, 'SELECT WITH GRANT OPTION') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_role.oid, admitted_relation.oid, 'INSERT WITH GRANT OPTION') "
        "OR "
        f"{maintain_definer} "
        "OR pg_catalog.has_table_privilege("
        "definer_role.oid, admitted_relation.oid, 'TRUNCATE') "
        "OR pg_catalog.has_table_privilege("
        "definer_role.oid, admitted_relation.oid, 'DELETE') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_role.oid, admitted_relation.oid, 'UPDATE') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_role.oid, admitted_relation.oid, 'REFERENCES') "
        "OR pg_catalog.has_table_privilege("
        "definer_role.oid, admitted_relation.oid, 'TRIGGER') "
        "OR "
        f"{privileged_definer_relation} "
        "OR EXISTS ("
        "WITH RECURSIVE definer_delegated_role(role_oid) AS ("
        "SELECT definer_admin_role.oid "
        "FROM pg_catalog.pg_roles AS definer_admin_role "
        "WHERE pg_catalog.pg_has_role("
        "definer_role.oid, definer_admin_role.oid, 'MEMBER WITH ADMIN OPTION') "
        "UNION "
        "SELECT definer_delegated_membership.roleid "
        "FROM definer_delegated_role "
        "JOIN pg_catalog.pg_auth_members AS definer_delegated_membership "
        "ON definer_delegated_membership.member OPERATOR(pg_catalog.=) "
        "definer_delegated_role.role_oid "
        "WHERE definer_delegated_membership.set_option "
        "OR definer_delegated_membership.admin_option"
        ") "
        "SELECT 1 FROM definer_delegated_role "
        "JOIN pg_catalog.pg_roles AS definer_delegated_role_details "
        "ON definer_delegated_role_details.oid OPERATOR(pg_catalog.=) "
        "definer_delegated_role.role_oid "
        "WHERE (definer_delegated_role_details.rolsuper "
        "OR definer_delegated_role_details.rolcreatedb "
        "OR definer_delegated_role_details.rolcreaterole "
        "OR definer_delegated_role_details.rolreplication "
        "OR definer_delegated_role_details.rolbypassrls "
        "OR definer_delegated_role_details.oid OPERATOR(pg_catalog.=) "
        "admitted_relation.relowner "
        "OR pg_catalog.pg_has_role("
        "definer_delegated_role_details.oid, admitted_relation.relowner, 'USAGE') "
        "OR pg_catalog.pg_has_role("
        "definer_delegated_role_details.oid, admitted_relation.relowner, 'SET') "
        "OR pg_catalog.pg_has_role("
        "definer_delegated_role_details.oid, admitted_relation.relowner, "
        "'MEMBER WITH ADMIN OPTION') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_delegated_role_details.oid, admitted_relation.oid, 'SELECT') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_delegated_role_details.oid, admitted_relation.oid, 'INSERT') "
        "OR "
        f"{maintain_definer_delegated} "
        "OR pg_catalog.has_table_privilege("
        "definer_delegated_role_details.oid, admitted_relation.oid, 'TRUNCATE') "
        "OR pg_catalog.has_table_privilege("
        "definer_delegated_role_details.oid, admitted_relation.oid, 'DELETE') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_delegated_role_details.oid, admitted_relation.oid, 'UPDATE') "
        "OR pg_catalog.has_any_column_privilege("
        "definer_delegated_role_details.oid, admitted_relation.oid, 'REFERENCES') "
        "OR pg_catalog.has_table_privilege("
        "definer_delegated_role_details.oid, admitted_relation.oid, 'TRIGGER') "
        "OR "
        f"{privileged_definer_delegated_relation})"
        "))) "
        "OR "
        f"{privileged_outbox_view} "
        "OR pg_catalog.has_any_column_privilege("
        "selectable_role.oid, admitted_relation.oid, 'SELECT WITH GRANT OPTION') "
        "OR pg_catalog.has_any_column_privilege("
        "selectable_role.oid, admitted_relation.oid, 'INSERT WITH GRANT OPTION') "
        "OR "
        f"{maintain_selectable} "
        "OR pg_catalog.has_table_privilege("
        "selectable_role.oid, admitted_relation.oid, 'TRUNCATE') "
        "OR pg_catalog.has_table_privilege("
        "selectable_role.oid, admitted_relation.oid, 'DELETE') "
        "OR pg_catalog.has_any_column_privilege("
        "selectable_role.oid, admitted_relation.oid, 'UPDATE') "
        "OR pg_catalog.has_any_column_privilege("
        "selectable_role.oid, admitted_relation.oid, 'REFERENCES') "
        "OR pg_catalog.has_table_privilege("
        "selectable_role.oid, admitted_relation.oid, 'TRIGGER')"
        ")), "
        "EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_roles AS selectable_role "
        "WHERE ("
        "selectable_role.rolname OPERATOR(pg_catalog.=) CURRENT_USER "
        "OR selectable_role.rolname OPERATOR(pg_catalog.=) SESSION_USER "
        "OR pg_catalog.pg_has_role("
        "SESSION_USER, selectable_role.oid, 'SET') "
        "OR pg_catalog.pg_has_role("
        "SESSION_USER, selectable_role.oid, 'MEMBER WITH ADMIN OPTION')"
        ") AND ("
        "selectable_role.rolsuper "
        "OR selectable_role.rolcreatedb "
        "OR selectable_role.rolcreaterole "
        "OR selectable_role.rolreplication "
        "OR selectable_role.rolbypassrls"
        ")"
        ") "
        "FROM pg_catalog.pg_class AS admitted_relation "
        "JOIN pg_catalog.pg_roles AS admitted_role "
        "ON admitted_role.rolname OPERATOR(pg_catalog.=) CURRENT_USER "
        "WHERE admitted_relation.oid OPERATOR(pg_catalog.=) "
        "pg_catalog.to_regclass('public.llm_context_lifecycle_outbox')"
    )
    role_row = cursor.fetchone()
    if type(role_row) is not tuple or role_row != (False, False):
        raise ConfigError(
            "Lifecycle outbox application role must have separated forced RLS authority"
        )


def _migration_file_error() -> ConfigError:
    """Return the fixed content-free migration-file authority error."""
    return ConfigError("Lifecycle outbox migration file is unavailable or unsafe")


def _migration_file_mode_is_safe(status: os.stat_result) -> bool:
    """Require regular SQL bytes that no group or other principal may rewrite."""
    return stat.S_ISREG(status.st_mode) and not (
        status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


def _migration_file_identity(status: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Snapshot stable metadata, including write authority, for one migration file."""
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
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
            not _migration_file_mode_is_safe(before)
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
    installation tooling; the package pins its descriptor, rejects group/other write
    authority, enforces a finite byte budget, and rejects observed mutation before
    SQL reaches PostgreSQL. Normal callers apply the package-owned base and
    row-admission-authority migrations in one database transaction.
    """
    dsn = _validated_postgres_dsn(postgres_dsn)
    _require_psycopg()
    paths = (
        (Path(migration_path),)
        if migration_path
        else (MIGRATION_PATH, _ROW_ADMISSION_AUTHORITY_MIGRATION_PATH)
    )
    sql_statements = tuple(_read_migration_sql(path) for path in paths)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for sql in sql_statements:
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
    not caller-writable instance slots. The database target may contain credentials,
    so it remains internal connection authority and has no public accessor. This keeps
    later SQL/RLS decisions bound to construction-time authority without making a DSN
    available to routine logging, serialization, or diagnostics. The concrete
    authority-bearing adapter is intentionally non-subclassable so inheritance cannot
    replace database/RLS properties through virtual dispatch; callers extend the
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
        with psycopg.connect(_OUTBOX_STORE_BINDINGS[self][0]) as conn:
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
        remains the compatibility name for serialized compare-and-swap reads, but the
        store uses a transaction-scoped advisory lock on the validated tenant/event
        identity rather than PostgreSQL ``SELECT ... FOR UPDATE``. That preserves
        package-level same-identity serialization without granting ambient ``UPDATE``
        authority over append-only durable evidence. Durable evidence is revalidated
        and must retain the tenant identity explicitly bound to this store before it
        can return to application code. Both the effective ``CURRENT_USER`` and the
        authenticated ``SESSION_USER`` role-selection closure must remain ordinary RLS
        subjects without outbox-owner, destructive, replication, database/role
        administration, delegable DML, relation-programming, caller-selectable
        privileged-view/materialized-copy/foreign-data, or executable privileged
        user-schema ``SECURITY DEFINER`` authority, while the canonical relation still
        has RLS enabled and forced with the sole reviewed tenant policy semantics. The
        read path pulls forward PostgreSQL's normal ``ACCESS SHARE`` relation lock
        before live admission and retains it through tenant binding and the consuming
        ``SELECT``. This keeps the relation identity admitted by the catalog proof from
        being renamed, replaced, dropped, or otherwise changed by concurrent DDL that
        requires ``ACCESS EXCLUSIVE`` between admission and the read. Security-critical
        function, relation, and policy authority is explicitly schema-qualified, and
        ``ONLY`` prevents inherited relations from widening the canonical durable row
        source if an inheritance edge appears after migration admission. The outbox
        does not mutate or inherit the caller transaction's ``search_path``.
        """
        if type(for_update) is not bool:
            raise ValidationError(
                field="for_update",
                value="<redacted>",
                reason="must be an exact boolean",
            )
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
        cursor.execute(
            "LOCK TABLE ONLY public.llm_context_lifecycle_outbox "
            "IN ACCESS SHARE MODE"
        )
        _require_rls_application_role(cursor)
        cursor.execute(
            "SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', %s, true)",
            (self.tenant_scope,),
        )
        if for_update:
            cursor.execute(
                "SELECT pg_catalog.pg_advisory_xact_lock(%s)",
                (_event_identity_lock_key(self.tenant_scope, probe.evidence_id),),
            )
            cursor.fetchone()
        cursor.execute(
            f"SELECT {_OUTBOX_COLUMNS} FROM ONLY public.llm_context_lifecycle_outbox "
            "WHERE tenant_scope = %s AND evidence_id = %s",
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
        with psycopg.connect(_OUTBOX_STORE_BINDINGS[self][0]) as conn:
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
        this store before any transaction-local SQL is executed. The write path pulls
        forward the table's normal ``ROW EXCLUSIVE`` DML lock before live authority
        admission and retains it through the caller transaction, preventing concurrent
        table-program or schema DDL from changing executable write authority between
        admission and the durable INSERT. The caller owns commit and rollback.
        """
        candidate = self._require_tenant_binding(
            _validated_evidence(evidence),
            durable_row=False,
        )
        cursor.execute(
            "LOCK TABLE ONLY public.llm_context_lifecycle_outbox "
            "IN ROW EXCLUSIVE MODE"
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
            "INSERT INTO public.llm_context_lifecycle_outbox ("
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
