# SPDX-License-Identifier: Apache-2.0
"""Privacy regressions for content-bearing count-tokens CLI input."""

from __future__ import annotations

import io
import json

import pytest

from pg_llm_batch import cli
from pg_llm_batch.exceptions import ConfigError


def _binary_stdin(payload: bytes) -> io.TextIOWrapper:
    """Return a UTF-8 text wrapper exposing an exact binary stdin buffer."""
    return io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")


def test_count_tokens_parser_requires_explicit_stdin_source() -> None:
    """Prompt content is not accepted as a count-tokens command-line value."""
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "count-tokens",
            "--dsn",
            "postgresql://unit",
            "--model",
            "gpt-4o",
            "--stdin",
        ]
    )

    assert args.command == "count-tokens"
    assert args.stdin is True
    assert not hasattr(args, "text")


def test_count_tokens_rejected_argv_content_is_not_reflected(capsys) -> None:
    """A legacy argv prompt is rejected without copying its content to stderr."""
    sentinel = "PROMPT-SECRET-4f74a49e"

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "count-tokens",
                "--model",
                "gpt-4o",
                "--text",
                sentinel,
            ]
        )

    assert sentinel not in capsys.readouterr().err


def test_count_tokens_stdin_preserves_exact_utf8_text(monkeypatch, capsys) -> None:
    """Bounded stdin preserves prompt text, including its final newline."""
    prompt = "café\nsecond line\n"
    events: list[object] = []

    class Store:
        """Closeable configuration double."""

        def __init__(self, dsn: str) -> None:
            events.append(("store", dsn))

        def close(self) -> None:
            events.append("store-close")

    class Counter:
        """Record the exact prompt handed to PostgreSQL token counting."""

        def __init__(self, dsn: str, config: object) -> None:
            events.append(("counter", dsn, config.__class__.__name__))

        def count_tokens(self, text: str, model: str) -> int:
            events.append(("count", text, model))
            return 7

        def close(self) -> None:
            events.append("counter-close")

    monkeypatch.setattr(cli, "PostgresConfigStore", Store)
    monkeypatch.setattr(cli, "TokenCounter", Counter)
    monkeypatch.setattr(cli.sys, "stdin", _binary_stdin(prompt.encode("utf-8")))

    assert cli._dispatch(
        [
            "count-tokens",
            "--dsn",
            "postgresql://unit",
            "--model",
            "gpt-4o",
            "--stdin",
        ]
    ) == 0

    assert ("count", prompt, "gpt-4o") in events
    assert events[-2:] == ["counter-close", "store-close"]
    assert json.loads(capsys.readouterr().out) == {"model": "gpt-4o", "tokens": 7}


def test_count_tokens_stdin_fails_closed_above_byte_limit(monkeypatch) -> None:
    """Oversized prompt bytes fail before configuration or token-counting I/O."""
    payload = b"x" * (cli.MAX_TOKEN_INPUT_BYTES + 1)
    opened: list[str] = []
    monkeypatch.setattr(cli.sys, "stdin", _binary_stdin(payload))
    monkeypatch.setattr(
        cli,
        "PostgresConfigStore",
        lambda _dsn: opened.append("config") or object(),
    )

    with pytest.raises(ConfigError, match="Token input exceeds byte limit"):
        cli._dispatch(
            [
                "count-tokens",
                "--dsn",
                "postgresql://unit",
                "--model",
                "gpt-4o",
                "--stdin",
            ]
        )

    assert opened == []


def test_count_tokens_stdin_rejects_invalid_utf8_without_content(monkeypatch) -> None:
    """Invalid UTF-8 fails with a fixed content-free diagnostic before DB I/O."""
    monkeypatch.setattr(cli.sys, "stdin", _binary_stdin(b"valid\xffsecret"))

    with pytest.raises(ConfigError, match="Token input must be valid UTF-8") as exc_info:
        cli._dispatch(
            [
                "count-tokens",
                "--dsn",
                "postgresql://unit",
                "--model",
                "gpt-4o",
                "--stdin",
            ]
        )

    assert "valid" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)
