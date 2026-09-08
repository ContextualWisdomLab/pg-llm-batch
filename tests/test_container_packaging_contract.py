# SPDX-License-Identifier: Apache-2.0
"""Container packaging contracts for strict PEP 639 metadata validation."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"


def test_component_builder_uses_reviewed_uv_toolchain_image() -> None:
    """The component image pins one semantic uv release by immutable digest."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    matches = re.findall(
        r"^FROM ghcr\.io/astral-sh/uv:(\d+\.\d+\.\d+)@sha256:([0-9a-f]{64}) AS uv$",
        text,
        flags=re.MULTILINE,
    )

    assert len(matches) == 1
    assert "ghcr.io/astral-sh/uv:latest" not in text


def test_component_builder_copies_declared_legal_files_before_sync() -> None:
    """The image build supplies every file declared by project.license-files."""
    text = DOCKERFILE.read_text(encoding="utf-8")

    metadata_copy = "COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./"
    assert metadata_copy in text
    assert text.index(metadata_copy) < text.index("RUN uv sync --frozen --no-dev --no-editable")


def test_component_runtime_does_not_install_libpq() -> None:
    """The pg8000 production image must not retain the superseded libpq runtime."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    runtime_stage = text.split("FROM python:3.14-slim@", maxsplit=2)[-1]

    assert re.search(r"(?:^|\s)libpq5(?:\s|$)", runtime_stage) is None
