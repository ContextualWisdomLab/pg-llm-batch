"""Public compatibility guards for checkpointed result application."""

from inspect import signature

from pg_llm_batch.result_application import ResultApplicationError


def test_result_application_error_keeps_phase_keyword_contract() -> None:
    """A later internal naming cleanup must not break the public error constructor."""
    constructor_parameters = tuple(signature(ResultApplicationError.__init__).parameters)

    assert constructor_parameters == ("self", "phase")
    error = ResultApplicationError(phase="checkpoint_load")
    assert error.details == {"phase": "checkpoint_load"}
