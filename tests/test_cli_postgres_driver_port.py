# SPDX-License-Identifier: Apache-2.0
"""CLI regressions for the PostgreSQL driver-migration boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pg_llm_batch import cli


class _CandidateConninfoError(Exception):
    """Candidate-driver parse failure used to exercise CLI normalization."""


class _CandidateDriver:
    """Minimal candidate parser double for the CLI migration seam."""

    def __init__(self) -> None:
        self.parsed_values: list[str] = []

    def parse_conninfo(self, value: str) -> dict[str, str]:
        """Parse bounded fixtures without delegating to Psycopg."""
        self.parsed_values.append(value)
        if value == "invalid":
            raise _CandidateConninfoError
        if value == "credential-bearing":
            return {"host": "db.internal", "password": "redacted-fixture"}
        return {"host": "db.internal", "dbname": "batch"}

    def is_invalid_conninfo(self, error: BaseException) -> bool:
        """Classify only this double's explicit conninfo failure."""
        return type(error) is _CandidateConninfoError


def test_cli_parser_uses_injected_postgres_driver_for_dsn() -> None:
    """Candidate validation must not route DSN parsing back through Psycopg."""
    driver = _CandidateDriver()

    parser = cli.build_parser(postgres_driver=driver)
    args = parser.parse_args(["health", "--dsn", "candidate-selector"])

    assert args.dsn == "candidate-selector"
    assert driver.parsed_values == ["candidate-selector"]


def test_cli_parser_normalizes_candidate_conninfo_failure() -> None:
    """Driver-specific parse errors remain bounded argparse diagnostics."""
    driver = _CandidateDriver()
    parser = cli.build_parser(postgres_driver=driver)

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["health", "--dsn", "invalid"])

    assert exc_info.value.code == 2


def test_cli_parser_rejects_candidate_reported_credential_fields() -> None:
    """Driver migration must preserve the credential-free argv contract."""
    driver = _CandidateDriver()
    parser = cli.build_parser(postgres_driver=driver)

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["health", "--dsn", "credential-bearing"])

    assert exc_info.value.code == 2


def test_cli_module_has_no_eager_psycopg_import() -> None:
    """Importing the CLI must not itself require the retained legacy driver."""
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    direct_psycopg_imports = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Import)
            and any(alias.name == "psycopg" or alias.name.startswith("psycopg.") for alias in node.names)
        )
        or (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "psycopg" or node.module.startswith("psycopg."))
        )
    ]

    assert direct_psycopg_imports == []
