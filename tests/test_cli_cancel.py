# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the standalone provider batch cancellation command."""

from __future__ import annotations

import asyncio

from pg_llm_batch import cli


def test_cancel_command_routes_existing_client_primitive(monkeypatch) -> None:
    """The operator command must delegate to BatchAPIClient.cancel_batch exactly once."""
    calls: list[tuple[str, str]] = []

    class Client:
        async def cancel_batch(self, batch_id: str, endpoint_alias: str):
            calls.append((batch_id, endpoint_alias))
            return {"success": True, "batch_id": batch_id, "status": "cancelling"}

    def run_report(dsn: str, factory) -> int:
        assert dsn == "postgresql://operator"
        result = asyncio.run(factory(Client()))
        assert result == {
            "success": True,
            "batch_id": "batch-123",
            "status": "cancelling",
        }
        return 8

    monkeypatch.setattr(cli, "_run_async_report", run_report)

    assert (
        cli._dispatch(
            [
                "cancel",
                "--dsn",
                "postgresql://operator",
                "--endpoint",
                "default",
                "--batch-id",
                "batch-123",
            ]
        )
        == 8
    )
    assert calls == [("batch-123", "default")]
