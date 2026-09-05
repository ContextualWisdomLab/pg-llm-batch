# SPDX-License-Identifier: Apache-2.0
"""Container-install contracts for the durable Context lifecycle outbox."""

from pathlib import Path


PACKAGE_SQL = Path("pg_llm_batch/migrations/0008_context_lifecycle_outbox.sql")
DOCKER_SQL = Path("docker/postgres/init/04_context_lifecycle_outbox.sql")
DOCKERFILE = Path("docker/postgres/Dockerfile")


def test_packaged_and_container_outbox_migrations_are_identical() -> None:
    """Package and deployable PostgreSQL images must install identical outbox bytes."""
    assert PACKAGE_SQL.is_file()
    assert DOCKER_SQL.is_file()
    assert PACKAGE_SQL.read_bytes() == DOCKER_SQL.read_bytes()


def test_outbox_migration_uses_canonical_lifecycle_timestamp_identity() -> None:
    """Database checks must enforce the package's exact canonical UTC identity."""
    schema = PACKAGE_SQL.read_text(encoding="utf-8")

    assert schema.count(r"([.]\d{6})?Z$") == 2
    assert r"\d{1,6}" not in schema
    assert schema.count("AT TIME ZONE 'UTC'") == 2
    assert schema.count("!~ '[.]000000Z$'") == 2
    assert schema.count("HH24:MI:SS.US") == 2
    assert schema.count("HH24:MI:SS\"Z\"") == 2


def test_postgres_image_installs_outbox_after_checkpoint_schema() -> None:
    """Fresh container databases must receive the outbox after its prerequisites."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    checkpoint_init = (
        "COPY init/03_result_stream_checkpoints.sql "
        "/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql"
    )
    outbox_init = (
        "COPY init/04_context_lifecycle_outbox.sql "
        "/docker-entrypoint-initdb.d/05_context_lifecycle_outbox.sql"
    )
    assert checkpoint_init in dockerfile
    assert outbox_init in dockerfile
    assert dockerfile.index(checkpoint_init) < dockerfile.index(outbox_init)
