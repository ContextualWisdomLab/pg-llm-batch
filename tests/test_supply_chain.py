# SPDX-License-Identifier: Apache-2.0
"""Regression tests for immutable container and downloaded-code inputs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_component_image_uses_locked_uv_and_digest_pinned_bases() -> None:
    """Keep runtime installation frozen and remove vulnerable build tooling."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM ") == 3
    assert dockerfile.count("@sha256:") == 3
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "pip install" not in dockerfile
    assert "site-packages/pip*" in dockerfile
    assert "apt-get upgrade -y" in dockerfile


def test_postgres_image_pins_and_verifies_every_executable_input() -> None:
    """Prevent mutable images, branches, and download-then-run pipelines."""
    dockerfile = (ROOT / "docker" / "postgres" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert dockerfile.count("FROM ") == 4
    assert dockerfile.count("@sha256:") == 2
    assert "FROM postgres-base AS with-tiktoken" in dockerfile
    assert "FROM postgres-base AS runtime" in dockerfile
    assert "PG_TIKTOKEN_COMMIT=0baf8d46620c9fa21acf4dc5f167e25f693aa932" in dockerfile
    assert 'test "$(git rev-parse HEAD)" = "${PG_TIKTOKEN_COMMIT}"' in dockerfile
    assert "cargo install --locked cargo-pgrx --version 0.16.1" in dockerfile
    assert "cargo generate-lockfile" in dockerfile
    assert "cargo fetch --locked" in dockerfile
    assert "cargo pgrx install --release;" in dockerfile
    assert "cargo pgrx install --release --locked" not in dockerfile
    assert "CARGO_HOME=/usr/local/cargo" in dockerfile
    assert "RUSTUP_HOME=/usr/local/rustup" in dockerfile
    assert "RUN bash -c 'set -euxo pipefail" in dockerfile
    assert "bash -lc" not in dockerfile
    assert "command -v cargo" in dockerfile
    assert "cargo --version" in dockerfile
    assert "rustc --version" in dockerfile
    assert "curl https://sh.rustup.rs" not in dockerfile
    assert "PG_TIKTOKEN_BRANCH" not in dockerfile
    assert "build failed; continuing" not in dockerfile
    assert "apt-get upgrade -y" in dockerfile
    assert "apt-get purge -y --auto-remove" in dockerfile
    assert "/usr/local/bin/gosu" in dockerfile


def test_o200k_patch_pins_compatible_transitive_git_dependency() -> None:
    """Pin a released tokenizer API that actually provides o200k support."""
    patch = (
        ROOT / "docker" / "postgres" / "patches" / "pg_tiktoken_o200k.patch"
    ).read_text(encoding="utf-8")
    added_lines = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )

    assert "o200k_base" in added_lines
    assert "https://github.com/zurawiki/tiktoken-rs" in added_lines
    assert "32de8dc0526d67f2c266c4e5e7c6a8ec5a0ce3d7" in added_lines
    assert "bpe_for_model" in added_lines
    assert "get_bpe_from_model" not in added_lines
    assert "https://github.com/kelvich/tiktoken-rs" not in added_lines
