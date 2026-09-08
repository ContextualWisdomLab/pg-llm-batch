"""Remaining authority edges for the commercial PostgreSQL driver migration."""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest

from pg_llm_batch.pg8000_driver_candidate_adapter import (
    Pg8000CandidateConnectionAdapter,
)
from pg_llm_batch.pg8000_driver_candidate_errors import (
    is_pg8000_candidate_undefined_function,
)
from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS,
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
)


def _candidate_module() -> ModuleType:
    """Build exact DB-API error authority without importing the candidate package."""
    module = ModuleType("candidate_pg8000_errors")

    class ProgrammingErrorCandidate(Exception):
        pass

    module.ProgrammingError = ProgrammingErrorCandidate
    return module


class _TransactionConnection:
    """Inject transaction and cleanup failures without a database."""

    def __init__(
        self,
        *,
        commit_error: BaseException | None = None,
        rollback_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.autocommit = False

    def cursor(self) -> Any:
        raise AssertionError("not used")

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error


def test_candidate_exit_preserves_transaction_error_over_cleanup_error() -> None:
    """A failed commit remains the primary result if physical close also fails."""
    commit_error = RuntimeError("commit failed")
    adapter = Pg8000CandidateConnectionAdapter(
        _TransactionConnection(
            commit_error=commit_error,
            close_error=OSError("close failed"),
        )
    )

    with pytest.raises(RuntimeError, match="commit failed") as caught:
        adapter.__exit__(None, None, None)
    assert caught.value is commit_error


def test_candidate_exit_preserves_application_error_over_cleanup_error() -> None:
    """A successful rollback cannot let a later close failure replace caller failure."""
    application_error = ValueError("application failed")
    adapter = Pg8000CandidateConnectionAdapter(
        _TransactionConnection(close_error=OSError("close failed"))
    )

    with pytest.raises(ValueError, match="application failed") as caught:
        adapter.__exit__(ValueError, application_error, None)
    assert caught.value is application_error


def test_candidate_error_classifier_rejects_wrong_exact_exception_type() -> None:
    """A message-compatible exception is never SQLSTATE authority."""
    module = _candidate_module()
    assert (
        is_pg8000_candidate_undefined_function(
            RuntimeError({"C": "42883"}),
            dbapi_module=module,
        )
        is False
    )


def test_candidate_evidence_rejects_unknown_capability_without_count_overflow() -> None:
    """Replacing one required capability with an unknown name hits set authority checks."""
    capabilities = set(REQUIRED_POSTGRES_DRIVER_CAPABILITIES)
    capabilities.remove(next(iter(capabilities)))
    capabilities.add("unknown_capability")

    with pytest.raises(PostgresDriverCandidateEvidenceError, match="unknown capability"):
        PostgresDriverCandidateEvidence(
            package_name="candidate-driver",
            package_version="1.2.3",
            license_spdx="BSD-3-Clause",
            license_report_sha256="d" * 64,
            python_versions=tuple(sorted(REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS)),
            source_commit_sha="a" * 40,
            artifact_sha256="b" * 64,
            vulnerability_report_sha256="c" * 64,
            capability_report_sha256="e" * 64,
            known_vulnerability_ids=(),
            capabilities=frozenset(capabilities),
        )
