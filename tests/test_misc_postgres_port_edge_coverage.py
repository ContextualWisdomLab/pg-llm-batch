"""Residual edge contracts exposed by the PostgreSQL driver-port migration."""

from __future__ import annotations

import threading

import pytest

from pg_llm_batch import cli, compose_bootstrap, db
from pg_llm_batch.exceptions import ConfigError
from pg_llm_batch.token_counter import TokenCounter


class _NonSelectorFailureDriver:
    """Raise a non-conninfo failure so CLI classification cannot swallow it."""

    def parse_conninfo(self, _dsn: str):
        raise RuntimeError("driver defect")

    def is_invalid_conninfo(self, _error: BaseException) -> bool:
        return False


def test_cli_propagates_non_selector_driver_failure() -> None:
    """Unexpected concrete-driver defects remain distinguishable from bad argv."""
    with pytest.raises(RuntimeError, match="driver defect"):
        cli.validate_cli_dsn("host=localhost", postgres_driver=_NonSelectorFailureDriver())


class _BootstrapConfigFailureDriver:
    """Raise an existing domain configuration error during private DSN assembly."""

    def parse_conninfo(self, _dsn: str):
        raise ConfigError("policy rejected")


def test_compose_bootstrap_preserves_existing_config_error() -> None:
    """Private DSN assembly must not relabel an established configuration decision."""
    with pytest.raises(ConfigError, match="policy rejected"):
        compose_bootstrap.build_private_postgres_dsn(
            "host=localhost dbname=batch user=batch",
            "secret",
            postgres_driver=_BootstrapConfigFailureDriver(),
        )


@pytest.mark.parametrize("row_count", [True, -2, "1"])
def test_driver_neutral_row_count_rejects_non_exact_evidence(row_count: object) -> None:
    """Affected-row evidence never relies on truthiness or undocumented sentinels."""
    class Cursor:
        def row_count(self) -> object:
            return row_count

    assert db._cursor_row_count(Cursor(), None) is None


def test_token_counter_fails_closed_when_database_capability_is_already_unavailable() -> None:
    """A disabled retained session cannot be retried through an implicit fallback."""
    counter = TokenCounter.__new__(TokenCounter)
    counter._pg_available = False
    counter._pg_connection_lock = threading.Lock()

    with pytest.raises(RuntimeError, match="requires pg_tiktoken"):
        counter.count_tokens("nonempty", "model")
