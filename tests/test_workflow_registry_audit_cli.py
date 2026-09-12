# SPDX-License-Identifier: Apache-2.0
"""CLI exit-code and packaging contracts for the workflow registry audit."""

from __future__ import annotations

import json
from pathlib import Path

from pg_llm_batch.workflow_registry_audit import (
    WorkflowRegistryAuditError,
    main,
)

_PROTECTED_SHA = "a" * 40
_REPOSITORY = "ContextualWisdomLab/pg-llm-batch"


def test_main_prints_receipt_and_exits_zero_when_no_orphans(monkeypatch, capsys) -> None:
    """A clean live-ref receipt is JSON on stdout and exit status 0."""
    receipt = {
        "repository_full_name": _REPOSITORY,
        "protected_sha": _PROTECTED_SHA,
        "protected_ref": "main",
        "active_absent_workflows": [],
    }

    def fake_audit(**kwargs):
        assert kwargs["repository_full_name"] == _REPOSITORY
        assert kwargs["protected_ref"] == "main"
        assert kwargs["expected_protected_sha"] == _PROTECTED_SHA
        return receipt

    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.audit_live_protected_ref_workflows",
        fake_audit,
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert main(
        [
            "--repository",
            _REPOSITORY,
            "--protected-sha",
            _PROTECTED_SHA,
        ]
    ) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["active_absent_workflows"] == []


def test_main_exits_two_when_active_absent_candidates_exist(monkeypatch, capsys) -> None:
    """Operators get exit 2 so automation can fail a job without mutating workflows."""
    receipt = {
        "active_absent_workflows": [
            {
                "workflow_id": 9,
                "path": ".github/workflows/orphan.yml",
                "state": "active",
            }
        ]
    }
    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.audit_live_protected_ref_workflows",
        lambda **_kwargs: receipt,
    )

    assert main(
        [
            "--repository",
            _REPOSITORY,
            "--protected-sha",
            _PROTECTED_SHA,
            "--protected-ref",
            "release/1.0",
        ]
    ) == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["active_absent_workflows"][0]["path"] == ".github/workflows/orphan.yml"


def test_main_exits_one_and_prints_fixed_stderr_on_audit_error(monkeypatch, capsys) -> None:
    """Transport and classification failures stay body-free on stderr."""

    def boom(**_kwargs):
        raise WorkflowRegistryAuditError("protected ref moved during audit")

    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.audit_live_protected_ref_workflows",
        boom,
    )

    assert main(
        [
            "--repository",
            _REPOSITORY,
            "--protected-sha",
            _PROTECTED_SHA,
        ]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "workflow_registry_audit: protected ref moved during audit\n"


def test_main_forwards_github_token_and_timeout_to_read_client(monkeypatch) -> None:
    """The CLI reads GITHUB_TOKEN from the environment and never prints it."""
    seen: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, *, token, timeout_seconds):
            seen["token"] = token
            seen["timeout_seconds"] = timeout_seconds

    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.GitHubReadClient",
        _FakeClient,
    )
    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.audit_live_protected_ref_workflows",
        lambda **kwargs: {"active_absent_workflows": []},
    )
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test_token_not_for_output")

    assert main(
        [
            "--repository",
            _REPOSITORY,
            "--protected-sha",
            _PROTECTED_SHA,
            "--timeout-seconds",
            "7.5",
        ]
    ) == 0
    assert seen["token"] == "ghs_test_token_not_for_output"
    assert seen["timeout_seconds"] == 7.5


def test_checkout_shim_reexports_packaged_public_api() -> None:
    """A repository checkout can still import the historical module path."""
    import workflow_registry_audit as shim
    from pg_llm_batch import workflow_registry_audit as packaged

    assert shim.main is packaged.main
    assert shim.GitHubReadClient is packaged.GitHubReadClient
    assert shim.audit_repository_workflows is packaged.audit_repository_workflows


def test_pyproject_declares_workflow_audit_console_script() -> None:
    """Installed wheels must expose the operator command, not a checkout-only module."""
    config = Path("pyproject.toml").read_text(encoding="utf-8")
    assert (
        'pg-llm-batch-workflow-audit = "pg_llm_batch.workflow_registry_audit:main"'
        in config
    )
