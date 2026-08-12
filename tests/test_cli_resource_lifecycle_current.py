# SPDX-License-Identifier: Apache-2.0
"""Regression tests for current-main CLI-owned PostgreSQL resource lifecycles."""

from __future__ import annotations

import io
from typing import Any

import pytest

from pg_llm_batch import cli


class _ConfigStore:
    """Record config operations and deterministic connection cleanup."""

    events: list[tuple[Any, ...]] = []

    def __init__(self, dsn: str) -> None:
        """Record the explicit DSN used for the owned store."""
        self.events.append(("config-open", dsn))

    def set(self, category: str, key: str, value: Any) -> None:
        """Record a CLI configuration write."""
        self.events.append(("config-set", category, key, value))

    def get(self, category: str, key: str) -> str:
        """Record a CLI configuration read."""
        self.events.append(("config-get", category, key))
        return "stored"

    def close(self) -> None:
        """Record deterministic release of the configuration connection."""
        self.events.append(("config-close",))


class _SecretStore:
    """Record secret operations and deterministic connection cleanup."""

    events: list[tuple[Any, ...]] = []

    def __init__(self, dsn: str, fernet_key: str | None = None) -> None:
        """Record the explicit DSN and key presence without retaining key material."""
        self.events.append(("secret-open", dsn, fernet_key is not None))

    def set_secret(self, key: str, value: str) -> None:
        """Record only the secret identifier and plaintext length."""
        self.events.append(("secret-set", key, len(value)))

    def close(self) -> None:
        """Record deterministic release of the secret-store connection."""
        self.events.append(("secret-close",))


class _TokenCounter:
    """Record token counting and deterministic cached-session cleanup."""

    events: list[tuple[Any, ...]] = []
    should_fail = False

    def __init__(self, dsn: str, *, config: _ConfigStore) -> None:
        """Record that the counter depends on the owned config store."""
        assert isinstance(config, _ConfigStore)
        self.events.append(("counter-open", dsn))

    def count_tokens(self, text: str, model: str) -> int:
        """Return a stable count or raise the configured primary failure."""
        self.events.append(("count", text, model))
        if self.should_fail:
            raise RuntimeError("token count failed")
        return 2

    def close(self) -> None:
        """Record deterministic release of the token-counting connection."""
        self.events.append(("counter-close",))


def _install_sync_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install observable CLI-owned config, secret, and token collaborators."""
    _ConfigStore.events = []
    _SecretStore.events = []
    _TokenCounter.events = []
    _TokenCounter.should_fail = False
    monkeypatch.setattr(cli, "PostgresConfigStore", _ConfigStore)
    monkeypatch.setattr(cli, "SecretStore", _SecretStore)
    monkeypatch.setattr(cli, "TokenCounter", _TokenCounter)
    monkeypatch.setattr(cli, "resolve_secret_key", lambda: "configured-key")


def test_config_commands_close_owned_database_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every one-shot config command must release its package-owned store."""
    _install_sync_stores(monkeypatch)

    assert cli._dispatch(
        ["config", "set", "--dsn", "postgresql://x", "gateway", "url", "value"]
    ) == 0
    assert cli._dispatch(
        ["config", "get", "--dsn", "postgresql://x", "gateway", "url"]
    ) == 0
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("purpose-bound-secret\n"))
    assert cli._dispatch(
        [
            "config",
            "set-secret",
            "--dsn",
            "postgresql://x",
            "gateway_api_key.default",
        ]
    ) == 0

    assert _ConfigStore.events == [
        ("config-open", "postgresql://x"),
        ("config-set", "gateway", "url", "value"),
        ("config-close",),
        ("config-open", "postgresql://x"),
        ("config-get", "gateway", "url"),
        ("config-close",),
    ]
    assert _SecretStore.events == [
        ("secret-open", "postgresql://x", True),
        ("secret-set", "gateway_api_key.default", len("purpose-bound-secret")),
        ("secret-close",),
    ]


def test_count_tokens_closes_owned_resources_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful one-shot counting must close the counter before its config."""
    _install_sync_stores(monkeypatch)

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

    assert _TokenCounter.events == [
        ("counter-open", "postgresql://x"),
        ("count", "one two", "gpt-4o"),
        ("counter-close",),
    ]
    assert _ConfigStore.events[-1] == ("config-close",)


def test_count_tokens_closes_owned_resources_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A primary token failure must propagate after deterministic cleanup."""
    _install_sync_stores(monkeypatch)
    _TokenCounter.should_fail = True

    with pytest.raises(RuntimeError, match="token count failed"):
        cli._dispatch(
            [
                "count-tokens",
                "--dsn",
                "postgresql://x",
                "--model",
                "gpt-4o",
                "--text",
                "one two",
            ]
        )

    assert _TokenCounter.events[-1] == ("counter-close",)
    assert _ConfigStore.events[-1] == ("config-close",)


class _AsyncClient:
    """Expose an async client context whose shutdown order is observable."""

    def __init__(self, dsn: str, provider: Any, lifecycle: list[str]) -> None:
        """Record construction with a database-backed provider."""
        self.dsn = dsn
        self.provider = provider
        self.lifecycle = lifecycle

    async def __aenter__(self) -> "_AsyncClient":
        """Return this client from the HTTP lifecycle context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Record HTTP-client cleanup before database-store cleanup."""
        self.lifecycle.append("client-close")

    async def report(self) -> dict[str, bool]:
        """Return a deterministic async command result."""
        return {"ok": True}


def test_async_cli_client_closes_credential_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async command exit must close HTTP, secret, then config resources."""
    lifecycle: list[str] = []

    class Config(_ConfigStore):
        def close(self) -> None:
            lifecycle.append("config-close")

    class Secrets(_SecretStore):
        def close(self) -> None:
            lifecycle.append("secret-close")

    class Client(_AsyncClient):
        def __init__(self, dsn: str, provider: Any) -> None:
            super().__init__(dsn, provider, lifecycle)

    monkeypatch.setattr(cli, "PostgresConfigStore", Config)
    monkeypatch.setattr(cli, "SecretStore", Secrets)
    monkeypatch.setattr(cli, "resolve_secret_key", lambda: "key")
    monkeypatch.setattr(cli, "BatchAPIClient", Client)
    monkeypatch.setattr(
        cli,
        "config_credentials_provider",
        lambda config, secrets: ("provider", config, secrets),
    )

    assert cli._run_async_report(
        "postgresql://x", lambda client: client.report()
    ) == 0
    assert lifecycle == ["client-close", "secret-close", "config-close"]


def test_async_client_construction_failure_closes_partial_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial credential construction must release every completed owner."""
    lifecycle: list[str] = []

    class Config:
        def __init__(self, _dsn: str) -> None:
            lifecycle.append("config-open")

        def close(self) -> None:
            lifecycle.append("config-close")

    class BrokenSecrets:
        def __init__(self, _dsn: str, fernet_key: str | None = None) -> None:
            assert fernet_key == "key"
            lifecycle.append("secret-failed")
            raise RuntimeError("secret construction failed")

    monkeypatch.setattr(cli, "PostgresConfigStore", Config)
    monkeypatch.setattr(cli, "SecretStore", BrokenSecrets)
    monkeypatch.setattr(cli, "resolve_secret_key", lambda: "key")

    with pytest.raises(RuntimeError, match="secret construction failed"):
        cli._run_async_report("postgresql://x", lambda _client: None)

    assert lifecycle == ["config-open", "secret-failed", "config-close"]
