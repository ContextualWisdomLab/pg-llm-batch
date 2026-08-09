# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for owned PostgreSQL connection lifecycles."""

import ast
from pathlib import Path


DOCTORING = Path("docs/doctoring/orchestrator-connection-lifecycle.md")
CHANGELOG = Path("CHANGELOG.md")
CONFIG_SOURCE = Path("pg_llm_batch/config.py")


def _normalized(path: Path) -> str:
    """Return Markdown with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split())


def _class_docstring(path: Path, class_name: str) -> str:
    """Return one class docstring from source without importing dependencies."""
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return " ".join((ast.get_docstring(node) or "").split())
    raise AssertionError(f"missing class {class_name}")


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


def test_secret_store_docstring_preserves_fallback_confidentiality_boundary() -> None:
    """Public docs must not hide that no-key storage is obfuscation, not encryption."""
    docstring = _class_docstring(CONFIG_SOURCE, "SecretStore").lower()

    assert "fernet-encrypted at rest" in docstring
    assert "base64-obfuscated" in docstring
    assert "local/dev" in docstring


def test_configured_fernet_missing_dependency_is_documented_fail_closed() -> None:
    """Docs must distinguish intentional no-key fallback from failed encryption setup."""
    docstring = _class_docstring(CONFIG_SOURCE, "SecretStore").lower()
    doctoring = _normalized(DOCTORING).lower()
    changelog = _normalized(CHANGELOG).lower()

    assert "configured" in docstring
    assert "cryptography" in docstring
    assert "fail" in docstring
    assert "configured fernet" in doctoring
    assert "cryptography" in doctoring
    assert "fail closed" in doctoring
    assert "configured fernet" in changelog
    assert "fail closed" in changelog
