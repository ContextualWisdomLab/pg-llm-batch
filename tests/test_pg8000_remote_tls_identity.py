# SPDX-License-Identifier: Apache-2.0
"""Remote TLS policy regressions for the admitted pg8000 driver."""

from __future__ import annotations

import ssl
from types import ModuleType

import pytest

from pg_llm_batch.pg8000_driver_adapter import Pg8000DriverAdapter


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
