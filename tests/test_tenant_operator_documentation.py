# SPDX-License-Identifier: Apache-2.0
"""Static contracts for tenant lifecycle operator documentation."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REMOTE_LIFECYCLE_GUIDE = REPOSITORY_ROOT / "docs" / "remote-batch-lifecycle.md"
README_PATH = REPOSITORY_ROOT / "README.md"
ARCHITECTURE_PATH = REPOSITORY_ROOT / "ARCHITECTURE.md"
DOCTORING_PATH = (
    REPOSITORY_ROOT / "docs" / "doctoring" / "tenant-scoped-lifecycle.md"
)
RUNTIME_ROLE_DOCTORING_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "doctoring"
    / "lifecycle-outbox-runtime-role-authority.md"
)
IMPLEMENTATION_PLAN_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-08-05-tenant-scoped-lifecycle.md"
)


def _read(path: Path) -> str:
    """Return one authoritative Markdown document as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    """Return Markdown with insignificant whitespace collapsed."""
    return " ".join(_read(path).split())


def test_remote_lifecycle_guide_exposes_tenant_qualified_operations() -> None:
    """The operator guide must describe the public tenant client and triple key."""
    guide = _normalized(REMOTE_LIFECYCLE_GUIDE)

    assert "TenantDurableBatchAPIClient" in guide
    assert "(tenant_scope, endpoint_alias, remote_batch_id)" in guide
    assert "get_tenant_remote_batch_state" in guide
    assert "persist_tenant_remote_batch_state" in guide
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in guide
    assert "direct SQL" in guide
    assert "arbitrary tenant scope" in guide


def test_readme_exposes_standalone_and_tenant_scoped_entry_points() -> None:
    """The first-run guide must make both deployment modes discoverable."""
    readme = _normalized(README_PATH)

    assert "DurableBatchAPIClient" in readme
    assert "TenantDurableBatchAPIClient" in readme
    assert "tenant_scope=" in readme
    assert "docs/remote-batch-lifecycle.md" in readme
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in readme


def test_architecture_and_doctoring_bound_the_custom_guc_claim() -> None:
    """RLS documentation must not imply protection from arbitrary SQL execution."""
    architecture = _normalized(ARCHITECTURE_PATH)
    doctoring = _normalized(DOCTORING_PATH)

    for document in (architecture, doctoring):
        assert "arbitrary SQL" in document
        assert "set_config" in document
        assert "trusted application boundary" in document
        assert "not a substitute" in document


def test_runtime_role_doctoring_includes_createrole_definer_boundary() -> None:
    """Operator evidence must cover indirect role administration through definers."""
    doctoring = _normalized(RUNTIME_ROLE_DOCTORING_PATH)

    assert "SECURITY DEFINER" in doctoring
    assert "CREATEROLE" in doctoring
    assert "NOCREATEROLE" in doctoring
    assert "createrole_self_grant" in doctoring
    assert "554189734a8ef257ba9a496f984866f2fea03709" in doctoring


def test_runtime_role_doctoring_includes_replication_definer_boundary() -> None:
    """Operator evidence must cover indirect replication-slot authority through definers."""
    doctoring = _normalized(RUNTIME_ROLE_DOCTORING_PATH)

    assert "SECURITY DEFINER" in doctoring
    assert "REPLICATION" in doctoring
    assert "NOREPLICATION" in doctoring
    assert "pg_create_physical_replication_slot" in doctoring
    assert "c5c9761583ef91a34d6f3ca5fb1c7d86c935037a" in doctoring


def test_docs_include_definer_membership_admin_delegation_boundary() -> None:
    """Architecture and operator evidence must retain the callable ADMIN escape proof."""
    architecture = _normalized(ARCHITECTURE_PATH)
    doctoring = _normalized(RUNTIME_ROLE_DOCTORING_PATH)

    for document in (architecture, doctoring):
        assert "MEMBER WITH ADMIN OPTION" in document
        assert "INHERIT FALSE, SET FALSE" in document
        assert "all-`SET TRUE`" in document
        assert "SECURITY DEFINER" in document
    assert "cba5f92a62f91c6aecee2c2c68f9f1cfcda25e6c" in doctoring
    assert "988ed9b611bc442891e9769ae86a0caf63764ab3" in doctoring


def test_migration_plan_preserves_atomic_default_deny_rls_order() -> None:
    """The implementation plan must preserve the reviewed default-deny RLS order."""
    plan = _normalized(IMPLEMENTATION_PLAN_PATH)

    required_order = (
        "owner-enforcement relaxation, legacy backfill, constraint migration, "
        "RLS enable and force, policy recreation under default-deny, and "
        "forced-RLS restoration"
    )
    assert required_order in plan
    assert "same PostgreSQL statement" in plan
    assert "Enable and force RLS after the policy is present" not in plan
