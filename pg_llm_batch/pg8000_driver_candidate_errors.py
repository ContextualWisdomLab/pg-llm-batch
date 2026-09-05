"""Candidate-only pg8000 PostgreSQL error classification.

The production package still uses Psycopg while the commercial driver migration
is incomplete.  This module proves only narrow pg8000 error semantics needed by
``PostgresDriverPort`` without importing pg8000 into the committed runtime
dependency graph.  Callers must inject the exact admitted DB-API module from the
candidate environment; message text is never used as authority.
"""

from __future__ import annotations

from types import ModuleType


_UNDEFINED_FUNCTION_SQLSTATE = "42883"


class Pg8000CandidateErrorEvidenceError(RuntimeError):
    """Reject malformed candidate exception authority before classification.

    Candidate metadata participates in a commercial dependency decision.  An
    invalid module or exception-class authority therefore fails closed instead
    of being interpreted as a PostgreSQL server error or a successful parity
    result.
    """


def _programming_error_type(dbapi_module: object) -> type[BaseException]:
    """Return the exact DB-API ProgrammingError class from an admitted module.

    ``ModuleType`` identity is required so shaped objects cannot execute custom
    attribute access while supplying security-relevant error metadata.  The
    exported class must be an actual ``BaseException`` subtype before any
    candidate exception is inspected.
    """
    if type(dbapi_module) is not ModuleType:
        raise Pg8000CandidateErrorEvidenceError(
            "PostgreSQL candidate DB-API module authority is invalid"
        )
    programming_error = vars(dbapi_module).get("ProgrammingError")
    if (
        type(programming_error) is not type
        or not issubclass(programming_error, BaseException)
    ):
        raise Pg8000CandidateErrorEvidenceError(
            "PostgreSQL candidate ProgrammingError authority is invalid"
        )
    return programming_error


def is_pg8000_candidate_undefined_function(
    error: BaseException,
    *,
    dbapi_module: object,
) -> bool:
    """Recognize only PostgreSQL SQLSTATE 42883 from the exact candidate class.

    pg8000 server errors carry a PostgreSQL response mapping as the sole
    ``ProgrammingError`` argument.  Classification requires the exact injected
    DB-API exception type, an exact built-in ``dict`` payload, and an exact
    string SQLSTATE.  Severity and message text are intentionally ignored, so
    translated or attacker-controlled diagnostics cannot manufacture the
    undefined-function fallback signal used by token-counting code.

    Raises:
        Pg8000CandidateErrorEvidenceError: If the injected DB-API module does not
            expose a trustworthy ``ProgrammingError`` class authority.
    """
    programming_error = _programming_error_type(dbapi_module)
    if type(error) is not programming_error:
        return False
    arguments = error.args
    if type(arguments) is not tuple or len(arguments) != 1:
        return False
    payload = arguments[0]
    if type(payload) is not dict:
        return False
    sqlstate = payload.get("C")
    return type(sqlstate) is str and sqlstate == _UNDEFINED_FUNCTION_SQLSTATE
