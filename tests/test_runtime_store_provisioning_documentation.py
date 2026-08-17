# SPDX-License-Identifier: Apache-2.0
"""Static contracts for runtime-store provisioning operator documentation."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPOSITORY_ROOT / "README.md"
ARCHITECTURE_PATH = REPOSITORY_ROOT / "ARCHITECTURE.md"
CHANGELOG_PATH = REPOSITORY_ROOT / "CHANGELOG.md"
DOCTORING_PATH = (
    REPOSITORY_ROOT / "docs" / "doctoring" / "runtime-store-provisioning.md"
)
BOOTSTRAP_DOCTORING_PATH = (
    REPOSITORY_ROOT / "docs" / "doctoring" / "bootstrap-dsn-precedence.md"
)
BOOTSTRAP_MODULE_PATH = REPOSITORY_ROOT / "pg_llm_batch" / "bootstrap.py"
CONFIG_MODULE_PATH = REPOSITORY_ROOT / "pg_llm_batch" / "config.py"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"


def _read(path: Path) -> str:
    """Return one authoritative text file as UTF-8."""
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    """Return text with insignificant whitespace collapsed."""
    return " ".join(_read(path).split())


def test_operator_docs_require_fernet_and_explicit_provisioning() -> None:
    """First-run and architecture docs must not describe optional encryption."""
    readme = _normalized(README_PATH)
    architecture = _normalized(ARCHITECTURE_PATH)
    changelog = _normalized(CHANGELOG_PATH)

    assert "optional Fernet key" not in readme
    assert "required Fernet key" in readme
    assert "SecretStore(dsn, fernet_key=fernet_key)" in readme
    assert "cryptography" in readme
    assert "do not create tables or seed defaults" in readme

    assert "do not provision schema" in architecture
    assert "require_encryption=False" in architecture
    assert "Base64" in architecture
    assert "NOSUPERUSER NOBYPASSRLS" in architecture

    assert "SecretStore" in changelog
    assert "Fernet" in changelog
    assert "Base64" in changelog
    assert "init-db" in changelog


def test_bootstrap_and_packaging_match_mandatory_encryption() -> None:
    """Bootstrap and install metadata must not call cryptography optional."""
    bootstrap = _normalized(BOOTSTRAP_MODULE_PATH)
    bootstrap_doctoring = _normalized(BOOTSTRAP_DOCTORING_PATH)
    config_module = _read(CONFIG_MODULE_PATH)
    pyproject = _read(PYPROJECT_PATH)

    assert "optional Fernet key to decrypt" not in bootstrap
    assert "required to construct ``SecretStore``" in bootstrap
    assert "fails closed" in bootstrap
    assert "not a supported unencrypted persistence mode" in bootstrap_doctoring
    assert "optional cryptography dependency" not in config_module
    assert "cryptography>=50.0.0" in pyproject.split("[project.optional-dependencies]")[0]


def test_runtime_store_doctoring_names_write_and_sql_boundaries() -> None:
    """Doctoring must tell operators the next repair action after a failed probe."""
    doctoring = _normalized(DOCTORING_PATH)

    assert "python -m pg_llm_batch init-db" in doctoring
    assert "NOSUPERUSER NOBYPASSRLS" in doctoring
    assert "does not assert `INSERT` or `UPDATE`" in doctoring
    assert "is_encrypted` explicitly to `TRUE`" in doctoring
    assert "core install dependency" in doctoring
    assert "require_encryption=False" in doctoring
