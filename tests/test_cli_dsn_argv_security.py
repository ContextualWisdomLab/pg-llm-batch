# SPDX-License-Identifier: Apache-2.0
"""Regression tests for PostgreSQL credential disclosure through CLI argv."""

from __future__ import annotations

import pytest

from pg_llm_batch import cli


@pytest.mark.parametrize(
    "credential_dsn",
    [
        "postgresql://app:secret-sentinel@db.example/batch",
        "postgres://app:secret-sentinel@db.example/batch",
        "host=db.example dbname=batch user=app password=secret-sentinel",
        "host=db.example dbname=batch user=app passfile=/tmp/secret-sentinel.pgpass",
    ],
)
def test_cli_rejects_credential_bearing_dsn_arguments_without_reflection(
    credential_dsn: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Credential-bearing DSNs fail in parsing without echoing sensitive argv."""
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["health", "--dsn", credential_dsn])

    captured = capsys.readouterr()
    assert "secret-sentinel" not in captured.err
    assert "secret-sentinel" not in captured.out


def test_cli_rejects_malformed_dsn_without_reflection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed conninfo fails with a fixed parser diagnostic."""
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["health", "--dsn", "host=db.example password=secret-sentinel broken"]
        )

    captured = capsys.readouterr()
    assert "secret-sentinel" not in captured.err
    assert "secret-sentinel" not in captured.out


@pytest.mark.parametrize(
    "selector",
    [
        "postgresql://db.example/batch?sslmode=verify-full",
        "host=db.example dbname=batch sslmode=verify-full",
        "service=pg-llm-batch",
    ],
)
def test_cli_retains_credential_free_explicit_database_selectors(selector: str) -> None:
    """Explicit database targeting remains usable when argv contains no secret."""
    args = cli.build_parser().parse_args(["health", "--dsn", selector])

    assert args.dsn == selector
