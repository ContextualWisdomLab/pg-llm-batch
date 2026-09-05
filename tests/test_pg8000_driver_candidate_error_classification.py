"""Candidate-only PostgreSQL error-classification contract tests.

These tests keep pg8000 out of the production dependency graph.  The exact
candidate artifact is injected as a DB-API module so the classifier can prove
one PostgreSQL SQLSTATE without trusting shaped exception objects or message
text.  Real PostgreSQL acceptance remains a separate CI smoke before candidate
promotion.
"""

from __future__ import annotations

from types import ModuleType

import pytest

from pg_llm_batch.pg8000_driver_candidate_errors import (
    Pg8000CandidateErrorEvidenceError,
    is_pg8000_candidate_undefined_function,
)


class _ProgrammingError(Exception):
    """Stand in for the exact candidate DB-API ProgrammingError class."""


def _dbapi_module() -> ModuleType:
    """Build one exact module-shaped DB-API authority for classifier tests."""
    module = ModuleType("pg8000.dbapi")
    module.ProgrammingError = _ProgrammingError
    return module


def test_candidate_classifies_only_exact_undefined_function_sqlstate() -> None:
    module = _dbapi_module()

    assert is_pg8000_candidate_undefined_function(
        _ProgrammingError({"S": "ERROR", "C": "42883", "M": "hidden"}),
        dbapi_module=module,
    ) is True
    assert is_pg8000_candidate_undefined_function(
        _ProgrammingError({"S": "ERROR", "C": "42P01", "M": "hidden"}),
        dbapi_module=module,
    ) is False


def test_candidate_classifier_rejects_untrusted_module_authority() -> None:
    with pytest.raises(
        Pg8000CandidateErrorEvidenceError,
        match="DB-API module authority is invalid",
    ):
        is_pg8000_candidate_undefined_function(
            _ProgrammingError({"C": "42883"}),
            dbapi_module=object(),
        )


def test_candidate_classifier_does_not_execute_or_trust_shaped_payloads() -> None:
    module = _dbapi_module()

    class _MappingLike:
        def get(self, key: object) -> object:
            raise AssertionError("mapping-like payload was evaluated")

    assert is_pg8000_candidate_undefined_function(
        _ProgrammingError(_MappingLike()),
        dbapi_module=module,
    ) is False
    assert is_pg8000_candidate_undefined_function(
        RuntimeError({"C": "42883"}),
        dbapi_module=module,
    ) is False


def test_candidate_classifier_rejects_malformed_programming_error_authority() -> None:
    module = _dbapi_module()
    module.ProgrammingError = "ProgrammingError"

    with pytest.raises(
        Pg8000CandidateErrorEvidenceError,
        match="ProgrammingError authority is invalid",
    ):
        is_pg8000_candidate_undefined_function(
            _ProgrammingError({"C": "42883"}),
            dbapi_module=module,
        )
