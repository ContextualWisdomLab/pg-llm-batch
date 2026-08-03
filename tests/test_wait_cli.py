# SPDX-License-Identifier: Apache-2.0
"""CLI coverage for bounded batch waiting."""

from __future__ import annotations

import asyncio

from pg_llm_batch import cli


def test_wait_command_routes_timing_options(monkeypatch):
    """The wait command forwards endpoint, batch, interval, and timeout values."""
    calls = []

    class Client:
        async def wait_for_batch(
            self,
            batch_id,
            endpoint_alias,
            *,
            poll_interval_seconds,
            timeout_seconds,
        ):
            calls.append(
                (
                    batch_id,
                    endpoint_alias,
                    poll_interval_seconds,
                    timeout_seconds,
                )
            )
            return {"status": "completed"}

    def run_report(dsn, factory):
        assert dsn == "postgresql://x"
        assert asyncio.run(factory(Client())) == {"status": "completed"}
        return 8

    monkeypatch.setattr(cli, "_run_async_report", run_report)

    assert (
        cli._dispatch(
            [
                "wait",
                "--dsn",
                "postgresql://x",
                "--endpoint",
                "azure",
                "--batch-id",
                "batch-1",
                "--poll-interval",
                "2.5",
                "--timeout",
                "90",
            ]
        )
        == 8
    )
    assert calls == [("batch-1", "azure", 2.5, 90.0)]
