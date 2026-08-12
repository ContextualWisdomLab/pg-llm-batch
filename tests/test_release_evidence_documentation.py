# SPDX-License-Identifier: Apache-2.0
"""Documentation contract for reproducible release acceptance."""

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0003-reproducible-release-evidence.md"
DOCTORING = ROOT / "docs" / "doctoring" / "reproducible-release-evidence.md"
UV_CONFIG = ROOT / "uv.toml"


def test_release_evidence_adr_separates_acceptance_from_publication() -> None:
    text = ADR.read_text(encoding="utf-8")

    assert "two clean exact-head builds" in text
    assert "SOURCE_DATE_EPOCH" in text
    assert "does not publish" in text
    assert "does not attest" in text
    assert "independent approval" in text


def test_release_evidence_documents_exact_build_toolchain() -> None:
    required_version = tomllib.loads(UV_CONFIG.read_text(encoding="utf-8"))[
        "required-version"
    ]
    assert required_version.startswith("==")
    uv_version = required_version.removeprefix("==")

    for path in (ADR, DOCTORING):
        text = path.read_text(encoding="utf-8")
        assert f"`uv` {uv_version}" in text
        assert "`uv_build==0.12.1`" in text
        assert "build-system requirements are not pinned by `uv.lock`" in text


def test_release_evidence_doctoring_defines_bounded_operator_evidence() -> None:
    text = DOCTORING.read_text(encoding="utf-8")

    required = (
        "release-manifest.json",
        "SHA-256",
        "exactly one wheel",
        "exactly one source distribution",
        "regular non-symlink",
        "14 days",
        "SLSA v1.2",
        "APA 7",
    )
    for phrase in required:
        assert phrase in text


def test_release_evidence_doctoring_rejects_stale_stacked_base_proof() -> None:
    text = DOCTORING.read_text(encoding="utf-8")

    required = (
        "current stacked base",
        "GitHub-generated merge commit",
        "stale-base",
        "retarget",
        "integrated main",
    )
    for phrase in required:
        assert phrase in text
