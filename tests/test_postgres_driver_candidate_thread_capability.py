"""Commercial-candidate concurrency evidence must match DB-API connection ownership.

A replacement driver can be permissively licensed and otherwise satisfy the SQL,
transaction, type, and conninfo contract while still declaring connections unsafe
to share across threads. Candidate admission therefore requires explicit evidence
for the connection thread-affinity policy instead of inferring concurrency safety
from module importability or successful single-thread PostgreSQL smokes.
"""

from __future__ import annotations

from pg_llm_batch.postgres_driver_candidate import (
    PostgresDriverCandidateEvidence,
    evaluate_postgres_driver_candidate,
)


_LEGACY_CAPABILITIES_WITHOUT_THREAD_AFFINITY = frozenset(
    {
        "autocommit_state",
        "connection_closed_state",
        "connection_context",
        "connection_context_commit_rollback",
        "conninfo_keyword_parse_render",
        "conninfo_service_selector",
        "conninfo_uri_parse_render",
        "cursor_context",
        "finite_connect_timeout",
        "invalid_conninfo_classification",
        "jsonb",
        "parameterized_sql",
        "result_row_semantics",
        "row_count",
        "sql_parameter_style_adaptation",
        "transaction_commit_rollback",
        "undefined_function_classification",
        "uuid_timestamp_adaptation",
    }
)


def test_candidate_requires_explicit_connection_thread_affinity_evidence() -> None:
    """Reject the former complete receipt when thread-ownership evidence is absent."""
    evidence = PostgresDriverCandidateEvidence(
        package_name="candidate-driver",
        package_version="1.2.3",
        license_spdx="BSD-3-Clause",
        license_report_sha256="d" * 64,
        python_versions=("3.10", "3.11", "3.12", "3.13", "3.14"),
        source_commit_sha="a" * 40,
        artifact_sha256="b" * 64,
        vulnerability_report_sha256="c" * 64,
        capability_report_sha256="e" * 64,
        known_vulnerability_ids=(),
        capabilities=_LEGACY_CAPABILITIES_WITHOUT_THREAD_AFFINITY,
    )

    decision = evaluate_postgres_driver_candidate(evidence)

    assert decision.eligible_for_parity_validation is False
    assert decision.production_approved is False
    assert decision.reasons == (
        "missing_capability:connection_thread_affinity",
    )
