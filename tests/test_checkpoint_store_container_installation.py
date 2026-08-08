# SPDX-License-Identifier: Apache-2.0
"""Regression tests for installing the durable checkpoint migration in the image."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE_PATH = REPOSITORY_ROOT / "docker" / "postgres" / "Dockerfile"
PACKAGE_MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "pg_llm_batch"
    / "migrations"
    / "0007_result_stream_checkpoints.sql"
)
CONTAINER_MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "docker"
    / "postgres"
    / "init"
    / "03_result_stream_checkpoints.sql"
)
CONTAINER_CHECKPOINT_COPY = (
    "COPY init/03_result_stream_checkpoints.sql "
    "/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql"
)
CONTAINER_CRON_COPY = (
    "COPY init/03_cron_batch_retrieval.sql "
    "/docker-entrypoint-initdb.d/03_cron_batch_retrieval.sql"
)


def test_checkpoint_migration_is_byte_identical_and_installed_in_image() -> None:
    """The bundled PostgreSQL image must execute the reviewed checkpoint migration."""
    package_sql = PACKAGE_MIGRATION_PATH.read_bytes()
    container_sql = CONTAINER_MIGRATION_PATH.read_bytes()
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert container_sql == package_sql
    assert dockerfile.count(CONTAINER_CHECKPOINT_COPY) == 1
    assert dockerfile.index(CONTAINER_CRON_COPY) < dockerfile.index(
        CONTAINER_CHECKPOINT_COPY
    )


def test_checkpoint_migration_uses_a_unique_init_destination() -> None:
    """Checkpoint initialization must not overwrite another entrypoint script."""
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    init_copy_lines = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.startswith("COPY init/")
        and "/docker-entrypoint-initdb.d/" in line
    ]
    destinations = [line.split()[-1] for line in init_copy_lines]

    assert CONTAINER_CHECKPOINT_COPY in init_copy_lines
    assert len(destinations) == len(set(destinations))
