# SPDX-License-Identifier: Apache-2.0
"""Regression tests for PostgreSQL credential disclosure through CLI argv."""

from __future__ import annotations

import pytest

from pg_llm_batch import cli


class _EmptyLexer:
    """Model an unexpected lexer result for the CLI fail-closed guard."""

    whitespace_split = False
    commenters = ""

    def __iter__(self):
        """Yield no fields from a non-empty selector."""
        return iter(())


@pytest.mark.parametrize(
    "credential_dsn",
    [
        "postgresql://app:secret-sentinel@db.example/batch",
        "postgres://app:secret-sentinel@db.example/batch",
        "host=db.example dbname=batch user=app password=secret-sentinel",
        "host=db.example dbname=batch user=app passfile=/tmp/secret-sentinel.pgpass",
        "host=db.example dbname=batch user=app sslkey=/tmp/secret-sentinel.key",
        "host=db.example dbname=batch user=app sslpassword=secret-sentinel",
        "host=db.example dbname=batch user=app oauth_client_secret=secret-sentinel",
        "postgresql://db.example/batch?%70assword=secret-sentinel",
        "host = db.example PASSWORD = secret-sentinel",
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


@pytest.mark.parametrize(
    "malformed_dsn",
    [
        "host=db.example password=secret-sentinel broken",
        "postgresql:db.example/batch",
        "mysql://db.example/batch",
        "postgresql://[broken/batch",
        "host='unterminated",
        "=missing-key",
        "   ",
    ],
)
def test_cli_rejects_malformed_dsn_without_reflection(
    malformed_dsn: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed selector syntax fails with a fixed non-reflecting diagnostic."""
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["health", "--dsn", malformed_dsn])

    captured = capsys.readouterr()
    assert "secret-sentinel" not in captured.err
    assert "secret-sentinel" not in captured.out
    assert "unterminated" not in captured.err
    assert "missing-key" not in captured.err


@pytest.mark.parametrize(
    "selector",
    [
        "postgresql://db.example/batch?sslmode=verify-full",
        "postgresql:///postgres",
        "postgresql://db.example/batch?&sslmode=verify-full",
        "host=db.example dbname=batch sslmode=verify-full",
        "host = db.example dbname = 'batch reporting' sslmode=verify-full",
        "host=db\\ example dbname=batch",
        "service=pg-llm-batch",
        "service = pg-llm-batch",
    ],
)
def test_cli_retains_credential_free_explicit_database_selectors(selector: str) -> None:
    """Credential-free targeting survives policy checks independent of connectability."""
    args = cli.build_parser().parse_args(["health", "--dsn", selector])

    assert args.dsn == selector


def test_cli_keyword_policy_accepts_an_explicit_empty_value() -> None:
    """Lexical policy must not invent a connection-validity rule for empty values."""
    args = cli.build_parser().parse_args(["health", "--dsn", "host ="])

    assert args.dsn == "host ="


def test_cli_policy_fails_closed_when_lexer_returns_no_fields(monkeypatch) -> None:
    """Unexpected lexical emptiness must not bypass the selector syntax boundary."""
    monkeypatch.setattr(cli.shlex, "shlex", lambda *_args, **_kwargs: _EmptyLexer())

    with pytest.raises(cli._CliDsnSyntaxError):
        cli._default_cli_dsn_parameter_names("host=db.example")


def test_serve_healthz_cli_defaults_to_loopback() -> None:
    """Direct CLI readiness serving must not bind every host interface by default."""
    args = cli.build_parser().parse_args(
        ["serve-healthz", "--dsn", "postgresql://db.example/batch"]
    )

    assert args.host == "127.0.0.1"


def test_serve_healthz_cli_allows_explicit_container_binding() -> None:
    """Container callers may deliberately request an all-interface listener."""
    args = cli.build_parser().parse_args(
        [
            "serve-healthz",
            "--dsn",
            "postgresql://db.example/batch",
            "--host",
            "0.0.0.0",
        ]
    )

    assert args.host == "0.0.0.0"
