# SPDX-License-Identifier: Apache-2.0
"""Security contracts for CLI secret ingestion."""

from __future__ import annotations

import io
import warnings

import pytest

from pg_llm_batch import cli
from pg_llm_batch.exceptions import ConfigError


def test_set_secret_parser_rejects_plaintext_value_in_process_argv(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rejected argv secrets must not be reflected through parser diagnostics."""
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
    output = capsys.readouterr()
    assert "visible-secret" not in output.out
    assert "visible-secret" not in output.err


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


class _InteractiveInput(io.StringIO):
    """TTY-like input that fails if production tries to read an echoed secret."""

    def isatty(self) -> bool:
        """Report an interactive controlling terminal."""
        return True

    def read(self, *args, **kwargs):
        """Reject ordinary stdin reads for interactive secret entry."""
        raise AssertionError("interactive secrets must use getpass")


def test_interactive_secret_uses_no_echo_getpass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interactive entry must use the terminal no-echo password primitive."""
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveInput())
    prompts: list[str] = []
    monkeypatch.setattr(
        cli.getpass,
        "getpass",
        lambda prompt: prompts.append(prompt) or "interactive-secret",
    )

    assert cli._read_secret_input() == "interactive-secret"
    assert prompts == ["Secret value: "]


def test_interactive_secret_refuses_getpass_echo_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A getpass echo fallback must fail before reading plaintext visibly."""
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveInput())
    fallback_reads: list[str] = []

    def insecure_getpass(prompt: str) -> str:
        assert prompt == "Secret value: "
        warnings.warn(
            "Can not control echo on the terminal.",
            cli.getpass.GetPassWarning,
            stacklevel=2,
        )
        fallback_reads.append("echoed")
        return "would-have-been-visible"

    monkeypatch.setattr(cli.getpass, "getpass", insecure_getpass)

    with pytest.raises(ConfigError, match="Echo-free"):
        cli._read_secret_input()
    assert fallback_reads == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain-secret", "plain-secret"),
        ("newline-secret\n", "newline-secret"),
        ("windows-secret\r\n", "windows-secret"),
    ],
)
def test_noninteractive_secret_accepts_one_bounded_logical_line(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: str,
) -> None:
    """Piped input accepts one line and removes only its terminal line ending."""
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(raw))
    assert cli._read_secret_input() == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "first\nsecond",
        "first\rsecond",
        "x" * 65_537,
    ],
)
def test_noninteractive_secret_fails_closed_on_unsafe_shape(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    """Empty, multiline, or oversized secrets are rejected without storage."""
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(raw))
    with pytest.raises(ConfigError):
        cli._read_secret_input()
