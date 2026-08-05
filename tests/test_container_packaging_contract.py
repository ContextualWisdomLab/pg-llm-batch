# SPDX-License-Identifier: Apache-2.0
"""Container packaging contracts for strict PEP 639 metadata validation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"


def test_component_builder_copies_declared_legal_files_before_sync() -> None:
    """The image build supplies every file declared by project.license-files."""
    text = DOCKERFILE.read_text(encoding="utf-8")

    metadata_copy = "COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./"
    assert metadata_copy in text
    assert text.index(metadata_copy) < text.index("RUN uv sync --frozen --no-dev --no-editable")
