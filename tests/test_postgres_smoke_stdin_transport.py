# SPDX-License-Identifier: Apache-2.0
"""Regression guard for PostgreSQL smoke-test stdin transport."""

from __future__ import annotations

from pathlib import Path


def test_docker_exec_psql_heredocs_attach_stdin() -> None:
    """Every psql heredoc must request Docker stdin attachment explicitly."""
    tests_dir = Path(__file__).parent
    violations: list[str] = []

    for script in sorted(tests_dir.glob("smoke_context_lifecycle_outbox_*.sh")):
        for line_number, line in enumerate(
            script.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if "docker exec" not in line or "psql" not in line or "<<" not in line:
                continue
            if "docker exec -i " not in line:
                violations.append(f"{script.name}:{line_number}: {line.strip()}")

    assert not violations, "psql heredoc(s) do not attach Docker stdin:\n" + "\n".join(
        violations
    )
