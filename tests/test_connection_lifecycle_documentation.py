# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for owned PostgreSQL connection lifecycles."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/orchestrator-connection-lifecycle.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Return Markdown with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_owned_connection_lifecycle_contract_is_authoritative() -> None:
    """Docs must preserve deterministic cleanup and acquisition ordering."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    assert "deterministic cleanup" in doctoring.lower()
    assert "try/finally" in doctoring
    assert "PostgresConfigStore" in doctoring
    assert "TokenCounter" in doctoring
    assert "configuration validation" in doctoring.lower()
    assert "before" in doctoring.lower()
    assert "pg_tiktoken" in doctoring
    assert "rollback" in doctoring.lower()
    assert "Psycopg Team. (2026)." in doctoring
    assert "Basic module usage" in doctoring
    assert "Python Software Foundation. (2026)." in doctoring
    assert "Compound statements" in doctoring
    assert "orchestrator-owned" in changelog.lower()
    assert "connection" in changelog.lower()


def test_partial_store_construction_cleanup_is_authoritative() -> None:
    """Docs must preserve cleanup after a store acquires but cannot initialize."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    assert "partially initialized" in doctoring.lower()
    assert "constructor" in doctoring.lower()
    assert "PostgresConfigStore" in doctoring
    assert "SecretStore" in doctoring
    assert "setup failure" in doctoring.lower()
    assert "store constructor" in changelog.lower()
