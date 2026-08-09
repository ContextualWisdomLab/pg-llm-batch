# SPDX-License-Identifier: Apache-2.0
"""Security contracts for CLI secret ingestion."""

from __future__ import annotations

import io

import pytest

from pg_llm_batch import cli


def test_set_secret_parser_rejects_plaintext_value_in_process_argv() -> None:
    """Secret plaintext must never be accepted as a command-line argument."""
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "config",
                "set-secret",
                "--dsn",
                "postgresql://example",
                "gateway_api_key.default",
                "visible-secret",
            ]
        )

    assert exc_info.value.code == 2


def test_set_secret_reads_noninteractive_value_from_standard_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Automation can pipe a secret without exposing it through process argv."""
    stored: list[tuple[str, str]] = []

    class Secrets:
        def __init__(self, dsn: str, fernet_key: str | None = None) -> None:
            assert dsn == "postgresql://example"
            assert fernet_key == "fernet-key"

        def set_secret(self, key: str, value: str) -> None:
            stored.append((key, value))

    monkeypatch.setattr(cli, "SecretStore", Secrets)
    monkeypatch.setattr(cli, "resolve_secret_key", lambda: "fernet-key")
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("piped-secret"))

    assert (
        cli._dispatch(
            [
                "config",
                "set-secret",
                "--dsn",
                "postgresql://example",
                "gateway_api_key.default",
            ]
        )
        == 0
    )
    assert stored == [("gateway_api_key.default", "piped-secret")]
    output = capsys.readouterr()
    assert "Secret stored." in output.out
    assert "piped-secret" not in output.out
    assert "piped-secret" not in output.err
