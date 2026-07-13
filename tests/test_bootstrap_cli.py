# SPDX-License-Identifier: Apache-2.0
"""Unit tests for bootstrap-only environment reads and CLI routing."""

from __future__ import annotations

import json
import runpy
from types import SimpleNamespace

import pytest

from pg_llm_batch import bootstrap, cli
from pg_llm_batch.exceptions import ConfigError


def test_bootstrap_precedence_and_missing_values(monkeypatch):
    """Explicit bootstrap values win and absent required DSNs explain failure."""
    monkeypatch.setenv(bootstrap.DSN_ENV_VAR, "postgresql://environment")
    monkeypatch.setenv(bootstrap.SECRET_KEY_ENV_VAR, "environment-key")
    assert bootstrap.resolve_dsn("postgresql://explicit") == "postgresql://explicit"
    assert bootstrap.resolve_dsn() == "postgresql://environment"
    assert bootstrap.resolve_secret_key("explicit-key") == "explicit-key"
    assert bootstrap.resolve_secret_key() == "environment-key"

    monkeypatch.delenv(bootstrap.DSN_ENV_VAR)
    monkeypatch.delenv(bootstrap.SECRET_KEY_ENV_VAR)
    with pytest.raises(ConfigError, match="Pass --dsn"):
        bootstrap.resolve_dsn()
    assert bootstrap.resolve_secret_key() is None


def test_main_maps_domain_error_to_stderr(monkeypatch, capsys):
    """Domain errors retain their reason and stable exit code."""
    monkeypatch.setattr(
        cli,
        "_dispatch",
        lambda _argv: (_ for _ in ()).throw(ConfigError("missing setting")),
    )
    assert cli.main(["health"]) == 2
    assert "[CONFIG_ERROR] missing setting" in capsys.readouterr().err


def test_init_and_config_commands(monkeypatch, capsys):
    """Database initialization and config commands route exact arguments."""
    events = []

    class Store:
        def __init__(self, dsn):
            events.append(("store", dsn))

        def set(self, category, key, value):
            events.append(("set", category, key, value))

        def get(self, category, key):
            events.append(("get", category, key))
            return "stored-value"

    class Secrets:
        def __init__(self, dsn, fernet_key=None):
            events.append(("secrets", dsn, fernet_key))

        def set_secret(self, key, value):
            events.append(("set-secret", key, value))

    monkeypatch.setattr(cli, "PostgresConfigStore", Store)
    monkeypatch.setattr(cli, "SecretStore", Secrets)
    monkeypatch.setattr(cli, "resolve_secret_key", lambda: "fernet")
    monkeypatch.setattr(cli.db, "apply_schema", lambda dsn: events.append(("schema", dsn)))

    assert cli._dispatch(["init-db", "--dsn", "postgresql://x"]) == 0
    assert cli._dispatch(
        ["config", "set", "--dsn", "postgresql://x", "gateway", "url", "v"]
    ) == 0
    assert cli._dispatch(
        ["config", "get", "--dsn", "postgresql://x", "gateway", "url"]
    ) == 0
    assert cli._dispatch(
        [
            "config",
            "set-secret",
            "--dsn",
            "postgresql://x",
            "gateway_api_key.default",
            "secret",
        ]
    ) == 0

    assert ("schema", "postgresql://x") in events
    assert ("set", "gateway", "url", "v") in events
    assert ("get", "gateway", "url") in events
    assert ("set-secret", "gateway_api_key.default", "secret") in events
    output = capsys.readouterr().out
    assert "Schema applied." in output
    assert "stored-value" in output
    assert "Secret stored." in output
    assert "gateway_api_key.default" not in output
    assert "secret" not in output


def test_count_health_and_server_commands(monkeypatch, capsys):
    """Synchronous operational commands emit machine-readable results."""
    class Counter:
        def __init__(self, dsn, config):
            assert dsn == "postgresql://x"
            assert config == "config"

        def count_tokens(self, text, model):
            assert (text, model) == ("one two", "gpt-4o")
            return 2

    monkeypatch.setattr(cli, "PostgresConfigStore", lambda _dsn: "config")
    monkeypatch.setattr(cli, "TokenCounter", Counter)
    assert cli._dispatch(
        [
            "count-tokens",
            "--dsn",
            "postgresql://x",
            "--model",
            "gpt-4o",
            "--text",
            "one two",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out) == {"model": "gpt-4o", "tokens": 2}

    monkeypatch.setattr(cli, "check_health", lambda _dsn: {"ready": False})
    assert cli._dispatch(["health", "--dsn", "postgresql://x"]) == 1
    assert json.loads(capsys.readouterr().out) == {"ready": False}

    served = []
    monkeypatch.setattr(
        cli,
        "serve_healthz",
        lambda dsn, host, port: served.append((dsn, host, port)),
    )
    assert cli._dispatch(
        [
            "serve-healthz",
            "--dsn",
            "postgresql://x",
            "--host",
            "127.0.0.1",
            "--port",
            "9090",
        ]
    ) == 0
    assert served == [("postgresql://x", "127.0.0.1", 9090)]


def test_async_command_routes(monkeypatch):
    """Submit, poll, and retrieve preserve endpoint and batch arguments."""
    calls = []
    monkeypatch.setattr(
        cli,
        "_run_submit",
        lambda dsn, args: calls.append(("submit", dsn, args.file_path)) or 7,
    )
    monkeypatch.setattr(
        cli,
        "_run_async_report",
        lambda dsn, factory: calls.append(("report", dsn, factory)) or 8,
    )
    assert cli._dispatch(
        [
            "submit",
            "--dsn",
            "postgresql://x",
            "--endpoint",
            "default",
            "--file-path",
            "memory://f1",
        ]
    ) == 7
    assert cli._dispatch(
        [
            "poll",
            "--dsn",
            "postgresql://x",
            "--endpoint",
            "default",
            "--batch-id",
            "b1",
        ]
    ) == 8
    assert cli._dispatch(
        [
            "retrieve",
            "--dsn",
            "postgresql://x",
            "--endpoint",
            "default",
            "--batch-id",
            "b1",
        ]
    ) == 8
    assert calls[0] == ("submit", "postgresql://x", "memory://f1")


class _AsyncClient:
    """Async context client used to exercise CLI coroutine helpers."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def upload_jsonl(self, file_path, endpoint):
        assert (file_path, endpoint) == ("memory://f1", "default")
        return {"id": "uploaded"}

    async def create_batch_job(self, file_id, endpoint_alias, *, endpoint=None):
        return {
            "id": "batch",
            "file_id": file_id,
            "alias": endpoint_alias,
            "endpoint": endpoint,
        }


def test_async_helpers_print_results(monkeypatch, capsys):
    """CLI coroutine helpers close clients and print structured reports."""
    client = _AsyncClient()
    monkeypatch.setattr(cli, "_make_client", lambda _dsn: client)
    args = SimpleNamespace(
        file_path="memory://f1",
        endpoint="default",
        batch_endpoint="/v1/chat/completions",
    )
    assert cli._run_submit("postgresql://x", args) == 0
    submit_output = json.loads(capsys.readouterr().out)
    assert submit_output["file"]["id"] == "uploaded"

    async def report_factory(received):
        assert received is client
        return {"when": "now"}

    assert cli._run_async_report("postgresql://x", report_factory) == 0
    assert json.loads(capsys.readouterr().out) == {"when": "now"}


def test_make_client_uses_database_backed_credentials(monkeypatch):
    """Client construction wires config and secrets without environment URLs."""
    events = []
    monkeypatch.setattr(cli, "PostgresConfigStore", lambda dsn: ("config", dsn))
    monkeypatch.setattr(
        cli,
        "SecretStore",
        lambda dsn, fernet_key=None: ("secrets", dsn, fernet_key),
    )
    monkeypatch.setattr(cli, "resolve_secret_key", lambda: "key")
    monkeypatch.setattr(
        cli,
        "config_credentials_provider",
        lambda config, secrets: ("provider", config, secrets),
    )
    monkeypatch.setattr(
        cli,
        "BatchAPIClient",
        lambda dsn, provider: events.append((dsn, provider)) or "client",
    )
    assert cli._make_client("postgresql://x") == "client"
    assert events[0][0] == "postgresql://x"


def test_unknown_dispatch_branch_returns_two(monkeypatch):
    """A parser extension with no handler fails closed."""
    parser = SimpleNamespace(
        parse_args=lambda _argv: SimpleNamespace(command="future", dsn="postgresql://x")
    )
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    assert cli._dispatch([]) == 2


def test_module_entrypoint_delegates_to_cli(monkeypatch):
    """python -m entrypoint exits with the CLI result."""
    monkeypatch.setattr(cli, "main", lambda: 9)
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("pg_llm_batch.__main__", run_name="__main__")
    assert exc_info.value.code == 9
    namespace = runpy.run_module("pg_llm_batch.__main__", run_name="not_main")
    assert namespace["main"]() == 9
