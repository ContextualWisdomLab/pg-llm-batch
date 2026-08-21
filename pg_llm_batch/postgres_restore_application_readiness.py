# SPDX-License-Identifier: Apache-2.0
"""Inspect database-side application prerequisites after an isolated restore."""

from __future__ import annotations

from dataclasses import dataclass, field
from weakref import WeakKeyDictionary


_READINESS_SQL = """
SELECT
    pg_catalog.current_database() IS NOT NULL,
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension AS extension
        WHERE extension.extname = 'pg_tiktoken'
    ),
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_row
        INNER JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = function_row.pronamespace
        INNER JOIN pg_catalog.pg_depend AS dependency
            ON dependency.objid = function_row.oid
        INNER JOIN pg_catalog.pg_extension AS extension
            ON extension.oid = dependency.refobjid
        WHERE function_row.oid = pg_catalog.to_regprocedure(
                  'tiktoken_count(text,text)'
              )
          AND dependency.classid = pg_catalog.to_regclass('pg_catalog.pg_proc')
          AND dependency.refclassid = pg_catalog.to_regclass('pg_catalog.pg_extension')
          AND dependency.deptype = 'e'
          AND extension.extname = 'pg_tiktoken'
          AND pg_catalog.has_schema_privilege(namespace.oid, 'USAGE')
          AND pg_catalog.has_function_privilege(function_row.oid, 'EXECUTE')
    ),
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_row
        INNER JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = function_row.pronamespace
        INNER JOIN pg_catalog.pg_depend AS dependency
            ON dependency.objid = function_row.oid
        INNER JOIN pg_catalog.pg_extension AS extension
            ON extension.oid = dependency.refobjid
        WHERE function_row.oid = pg_catalog.to_regprocedure(
                  'tiktoken_encode(text,text)'
              )
          AND dependency.classid = pg_catalog.to_regclass('pg_catalog.pg_proc')
          AND dependency.refclassid = pg_catalog.to_regclass('pg_catalog.pg_extension')
          AND dependency.deptype = 'e'
          AND extension.extname = 'pg_tiktoken'
          AND pg_catalog.has_schema_privilege(namespace.oid, 'USAGE')
          AND pg_catalog.has_function_privilege(function_row.oid, 'EXECUTE')
    ),
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        INNER JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = pg_catalog.current_schema()
          AND relation.relname = 'com_config'
          AND relation.relkind = 'r'
          AND pg_catalog.has_schema_privilege(namespace.oid, 'USAGE')
          AND pg_catalog.has_table_privilege(relation.oid, 'SELECT')
    ),
    (
        SELECT COUNT(*)
        FROM pg_catalog.pg_proc AS function_row
        INNER JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = function_row.pronamespace
        WHERE namespace.nspname = pg_catalog.current_schema()
          AND function_row.proname = 'pg_llm_batch_health_check'
          AND function_row.pronargs = 0
          AND function_row.prokind = 'f'
    ),
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_row
        INNER JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = function_row.pronamespace
        WHERE namespace.nspname = pg_catalog.current_schema()
          AND function_row.proname = 'pg_llm_batch_health_check'
          AND function_row.pronargs = 0
          AND function_row.prokind = 'f'
          AND function_row.proretset
          AND function_row.prorettype = 'pg_catalog.record'::regtype
          AND function_row.proallargtypes = ARRAY[
                  'pg_catalog.text'::regtype::oid,
                  'pg_catalog.bool'::regtype::oid,
                  'pg_catalog.text'::regtype::oid
              ]::oid[]
          AND function_row.proargmodes = ARRAY[
                  't'::"char",
                  't'::"char",
                  't'::"char"
              ]
          AND function_row.proargnames = ARRAY[
                  'component',
                  'is_ready',
                  'detail'
              ]::text[]
          AND NOT function_row.prosecdef
          AND pg_catalog.has_schema_privilege(namespace.oid, 'USAGE')
          AND pg_catalog.has_function_privilege(function_row.oid, 'EXECUTE')
    )
""".strip()
_READINESS_OBSERVATION_MARK = object()
_READINESS_SNAPSHOT_TYPES = (bool, bool, bool, bool, bool, int, bool)


class PostgresRestoreApplicationReadinessError(ValueError):
    """Report a fail-closed restore application-readiness violation."""


@dataclass(frozen=True, eq=False)
class PostgresRestoreApplicationReadinessEvidence:
    """Represent content-free database-side readiness on an isolated target.

    Only ``inspect_postgres_restore_application_readiness`` registers an object
    as package-observed. Public construction, copying, or post-construction field
    mutation therefore cannot be reused as inspection provenance.
    """

    database_reachable: bool
    pg_tiktoken_extension_present: bool
    tiktoken_count_callable: bool
    tiktoken_encode_callable: bool
    config_table_readable: bool
    health_function_count: int
    health_function_executable: bool
    _observation_mark: object = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def as_dict(self) -> dict[str, object]:
        """Return the stable schema only for unchanged package-observed evidence."""
        (
            database_reachable,
            pg_tiktoken_extension_present,
            tiktoken_count_callable,
            tiktoken_encode_callable,
            config_table_readable,
            health_function_count,
            health_function_executable,
        ) = _require_observed_readiness(self)
        return {
            "database_reachable": database_reachable,
            "pg_tiktoken_extension_present": pg_tiktoken_extension_present,
            "tiktoken_count_callable": tiktoken_count_callable,
            "tiktoken_encode_callable": tiktoken_encode_callable,
            "config_table_readable": config_table_readable,
            "health_function_count": health_function_count,
            "health_function_executable": health_function_executable,
        }


_READINESS_SNAPSHOTS: WeakKeyDictionary[
    PostgresRestoreApplicationReadinessEvidence,
    tuple[bool, bool, bool, bool, bool, int, bool],
] = WeakKeyDictionary()


def _readiness_snapshot(
    evidence: PostgresRestoreApplicationReadinessEvidence,
) -> tuple[bool, bool, bool, bool, bool, int, bool]:
    """Capture behavior-bearing fields used to bind live observation provenance."""
    return (
        evidence.database_reachable,
        evidence.pg_tiktoken_extension_present,
        evidence.tiktoken_count_callable,
        evidence.tiktoken_encode_callable,
        evidence.config_table_readable,
        evidence.health_function_count,
        evidence.health_function_executable,
    )


def _provenance_error() -> PostgresRestoreApplicationReadinessError:
    """Build the fixed error used for invalid inspection provenance."""
    return PostgresRestoreApplicationReadinessError(
        "PostgreSQL restore application-readiness provenance is invalid"
    )


def _require_observed_readiness(
    evidence: PostgresRestoreApplicationReadinessEvidence,
) -> tuple[bool, bool, bool, bool, bool, int, bool]:
    """Return one validated snapshot or fail closed on fabricated evidence."""
    if type(evidence) is not PostgresRestoreApplicationReadinessEvidence:
        raise _provenance_error()
    try:
        if evidence._observation_mark is not _READINESS_OBSERVATION_MARK:
            raise _provenance_error()
        current_snapshot = _readiness_snapshot(evidence)
    except AttributeError:
        raise _provenance_error() from None
    if tuple(map(type, current_snapshot)) != _READINESS_SNAPSHOT_TYPES:
        raise _provenance_error()
    if _READINESS_SNAPSHOTS.get(evidence) != current_snapshot:
        raise _provenance_error()
    return current_snapshot


def _record_readiness_observation(
    evidence: PostgresRestoreApplicationReadinessEvidence,
) -> PostgresRestoreApplicationReadinessEvidence:
    """Mark and snapshot exactly one evidence object created from a live query row."""
    object.__setattr__(evidence, "_observation_mark", _READINESS_OBSERVATION_MARK)
    _READINESS_SNAPSHOTS[evidence] = _readiness_snapshot(evidence)
    return evidence


def _invalid_readiness_evidence() -> None:
    """Reject malformed database evidence without reflecting row contents."""
    raise PostgresRestoreApplicationReadinessError(
        "PostgreSQL restore application-readiness evidence is invalid"
    )


def _evaluate_readiness_row(
    row: object,
) -> PostgresRestoreApplicationReadinessEvidence:
    """Validate one fixed database-side application-readiness observation."""
    if type(row) is not tuple or len(row) != 7:
        _invalid_readiness_evidence()
    (
        database_reachable,
        pg_tiktoken_extension_present,
        tiktoken_count_callable,
        tiktoken_encode_callable,
        config_table_readable,
        health_function_count,
        health_function_executable,
    ) = row
    if (
        type(database_reachable) is not bool
        or type(pg_tiktoken_extension_present) is not bool
        or type(tiktoken_count_callable) is not bool
        or type(tiktoken_encode_callable) is not bool
        or type(config_table_readable) is not bool
        or type(health_function_count) is not int
        or type(health_function_executable) is not bool
    ):
        _invalid_readiness_evidence()
    if not database_reachable:
        raise PostgresRestoreApplicationReadinessError(
            "PostgreSQL restore target database is unavailable"
        )
    if (
        not pg_tiktoken_extension_present
        or not tiktoken_count_callable
        or not tiktoken_encode_callable
    ):
        raise PostgresRestoreApplicationReadinessError(
            "PostgreSQL restore target tokenizer is unavailable"
        )
    if not config_table_readable:
        raise PostgresRestoreApplicationReadinessError(
            "PostgreSQL restore target configuration is unavailable"
        )
    if health_function_count != 1 or not health_function_executable:
        raise PostgresRestoreApplicationReadinessError(
            "PostgreSQL restore target health contract is unavailable"
        )
    evidence = PostgresRestoreApplicationReadinessEvidence(
        database_reachable=database_reachable,
        pg_tiktoken_extension_present=pg_tiktoken_extension_present,
        tiktoken_count_callable=tiktoken_count_callable,
        tiktoken_encode_callable=tiktoken_encode_callable,
        config_table_readable=config_table_readable,
        health_function_count=health_function_count,
        health_function_executable=health_function_executable,
    )
    return _record_readiness_observation(evidence)


def inspect_postgres_restore_application_readiness(
    connection: object,
) -> PostgresRestoreApplicationReadinessEvidence:
    """Inspect fixed database-side prerequisites on a caller-owned restore target.

    ``connection`` is caller-owned and already connected to the isolated target.
    The function performs one fixed, read-only catalog query. It proves only that
    the current database is reachable, the resolved ``pg_tiktoken`` count/encode
    functions are extension-owned and callable through schema ``USAGE`` plus
    function ``EXECUTE`` authority, the current schema's ``com_config`` table is
    readable, and one zero-argument current-schema ``pg_llm_batch_health_check``
    function is callable by the current role and has the packaged set-returning
    ``TABLE(component TEXT, is_ready BOOLEAN, detail TEXT)`` catalog identity.
    Returned evidence is bound to the exact observed object and immutable field
    snapshot before it can be serialized.

    It does not invoke the health function, install extensions, grant privileges,
    change search paths, open another connection, start or promote recovery, test
    providers or external secret custody, prove exact PITR stop semantics, or
    establish end-user readiness, RPO/RTO, HA/DR, CSAP, SOC 2, or certification.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(_READINESS_SQL)
            row = cursor.fetchone()
    except Exception:
        raise PostgresRestoreApplicationReadinessError(
            "PostgreSQL restore application readiness could not be inspected"
        ) from None
    return _evaluate_readiness_row(row)
