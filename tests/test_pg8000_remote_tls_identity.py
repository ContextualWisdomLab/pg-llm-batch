# SPDX-License-Identifier: Apache-2.0
"""Remote TLS policy regressions for the admitted pg8000 driver."""

from __future__ import annotations

import ssl
from types import ModuleType, SimpleNamespace

import pytest

import pg_llm_batch.pg8000_driver_adapter as driver_module
from pg_llm_batch.pg8000_driver_adapter import (
    Pg8000DriverAdapter,
    Pg8000DriverTlsPolicyError,
)


class _RawConnection:
    """Stand in for a raw pg8000 connection without performing network I/O."""


def _dbapi_module(calls: list[dict[str, object]]) -> ModuleType:
    """Return the exact DB-API metadata shape plus a recording connect factory."""
    module = ModuleType("pg8000.dbapi")
    module.apilevel = "2.0"  # type: ignore[attr-defined]
    module.paramstyle = "format"  # type: ignore[attr-defined]
    module.threadsafety = 1  # type: ignore[attr-defined]

    def connect(**kwargs: object) -> _RawConnection:
        calls.append(dict(kwargs))
        return _RawConnection()

    module.connect = connect  # type: ignore[attr-defined]
    return module


def _connect_kwargs(host: str) -> dict[str, object]:
    """Open one fake connection and return the kwargs crossing into pg8000."""
    calls: list[dict[str, object]] = []
    adapter = Pg8000DriverAdapter(_dbapi_module(calls))
    adapter.connect(
        f"user=pgllm password=secret host={host} dbname=pgllm",
        connect_timeout_seconds=7,
    )
    assert len(calls) == 1
    return calls[0]


@pytest.mark.parametrize("host", ["db.example.invalid", "10.20.30.40", "192.168.50.10"])
def test_remote_tcp_requires_authenticated_tls(host: str) -> None:
    """Require CA and hostname verification for every non-loopback TCP target."""
    kwargs = _connect_kwargs(host)

    context = kwargs["ssl_context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert kwargs["host"] == host
    assert kwargs["timeout"] == 7


@pytest.mark.parametrize(
    "host",
    ["localhost", "LOCALHOST", "127.0.0.1", "127.42.0.9", "::1"],
)
def test_explicit_loopback_keeps_the_local_development_exception(host: str) -> None:
    """Keep plaintext fallback confined to explicit loopback selectors."""
    kwargs = _connect_kwargs(host)

    assert "ssl_context" not in kwargs
    assert kwargs["host"] == host


def test_remote_tls_context_construction_failure_is_content_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail before raw driver access when the host trust context cannot be built."""
    calls: list[dict[str, object]] = []
    adapter = Pg8000DriverAdapter(_dbapi_module(calls))

    def fail_context() -> ssl.SSLContext:
        raise OSError("secret certificate store path")

    monkeypatch.setattr(driver_module, "create_default_context", fail_context)

    with pytest.raises(
        Pg8000DriverTlsPolicyError,
        match="^PostgreSQL TLS policy is unavailable$",
    ):
        adapter.connect("user=pgllm host=db.example.invalid dbname=pgllm")

    assert calls == []


@pytest.mark.parametrize(
    "context",
    [
        SimpleNamespace(check_hostname=False, verify_mode=ssl.CERT_REQUIRED),
        SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_NONE),
    ],
)
def test_remote_rejects_weakened_tls_context(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
) -> None:
    """Reject a TLS context if either peer-identity invariant is disabled."""
    calls: list[dict[str, object]] = []
    adapter = Pg8000DriverAdapter(_dbapi_module(calls))
    monkeypatch.setattr(driver_module, "create_default_context", lambda: context)

    with pytest.raises(
        Pg8000DriverTlsPolicyError,
        match="^PostgreSQL TLS policy is unavailable$",
    ):
        adapter.connect("user=pgllm host=db.example.invalid dbname=pgllm")

    assert calls == []


def test_remote_tls_does_not_honor_ambient_key_logging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    """Keep process-level SSLKEYLOGFILE from becoming a package TLS key sink."""
    key_log_path = str(tmp_path / "postgres-tls.keys")  # type: ignore[operator]
    monkeypatch.setenv("SSLKEYLOGFILE", key_log_path)

    kwargs = _connect_kwargs("db.example.invalid")
    context = kwargs["ssl_context"]

    assert isinstance(context, ssl.SSLContext)
    assert context.keylog_filename is None
