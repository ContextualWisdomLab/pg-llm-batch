# SPDX-License-Identifier: Apache-2.0
"""Release-SBOM workflow contracts for the commercial PostgreSQL runtime graph."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_emits_validated_sbom_from_exact_production_environment() -> None:
    """Bind SBOM evidence to the no-dev Python 3.14 environment used for release parity."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert (
        "step-security/sbom-action@a2040c89fdf602b1abf5d2f46ac2c83bc6b341b7"
        in workflow
    )
    assert "syft-version: v1.51.1" in workflow
    assert "path: /tmp/pg8000-candidate-py314" in workflow
    assert "format: cyclonedx-json" in workflow
    assert "output-file: release-evidence/production-runtime.cdx.json" in workflow
    assert "upload-artifact: false" in workflow
    assert "upload-release-assets: false" in workflow
    assert "Verify production runtime SBOM policy" in workflow
    assert "production-runtime.cdx.json" in workflow
    assert 'component_name == "psycopg"' in workflow
    assert "GPL-family runtime dependency is disallowed" in workflow
    assert "Preserve production runtime SBOM" in workflow
    assert "release-sbom-${{ github.event.pull_request.head.sha || github.sha }}" in workflow
