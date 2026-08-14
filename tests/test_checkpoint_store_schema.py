# SPDX-License-Identifier: Apache-2.0
"""Static migration and rollback contracts for durable result checkpoints."""

from pathlib import Path

PACKAGE_SQL = Path("pg_llm_batch/migrations/0007_result_stream_checkpoints.sql")
DOCKER_SQL = Path("docker/postgres/init/03_result_stream_checkpoints.sql")
DOCKERFILE = Path("docker/postgres/Dockerfile")
ROLLBACK_SQL = Path("pg_llm_batch/migrations/rollback/0007_result_stream_checkpoints.sql")


def test_packaged_and_container_checkpoint_migrations_are_identical() -> None:
    """Package and container installs execute the same migration bytes."""
    assert PACKAGE_SQL.is_file()
    assert PACKAGE_SQL.read_bytes() == DOCKER_SQL.read_bytes()


def test_postgres_image_installs_checkpoint_migration_after_existing_init_steps() -> None:
    """The deployable image must actually install the mirrored checkpoint schema."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    existing_init = (
        "COPY init/03_cron_batch_retrieval.sql "
        "/docker-entrypoint-initdb.d/03_cron_batch_retrieval.sql"
    )
    checkpoint_init = (
        "COPY init/03_result_stream_checkpoints.sql "
        "/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql"
    )
    assert checkpoint_init in dockerfile
    assert dockerfile.index(existing_init) < dockerfile.index(checkpoint_init)


def test_checkpoint_schema_is_tenant_isolated_and_fail_closed() -> None:
    """The forward migration enforces tenant isolation and bounded fields."""
    sql = PACKAGE_SQL.read_text(encoding="utf-8")
    required = (
        "CREATE TABLE IF NOT EXISTS llm_result_stream_checkpoints",
        "checkpoint_consumer_name TEXT NOT NULL",
        "uq_llm_result_stream_checkpoints_tenant_consumer_batch",
        "UNIQUE (\n                tenant_scope,\n                checkpoint_consumer_name,\n                endpoint_alias,\n                remote_batch_id",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "plc_llm_result_stream_checkpoints_tenant_scope",
        "current_setting('pg_llm_batch.tenant_scope', true)",
        "prefix_sha256 ~ '^[0-9a-f]{64}$'",
        "record_count <= batch_line_count",
        "idx_llm_result_stream_checkpoints_tenant_updated",
    )
    for contract in required:
        assert contract in sql
    assert "BYPASSRLS" not in sql


def test_rollback_refuses_to_destroy_acknowledgement_evidence() -> None:
    """Rollback exposes owner-visible rows before its destructive emptiness check."""
    sql = ROLLBACK_SQL.read_text(encoding="utf-8")
    no_force = "ALTER TABLE llm_result_stream_checkpoints NO FORCE ROW LEVEL SECURITY"
    assert no_force in sql
    assert "EXISTS (" in sql
    assert "Refusing to drop non-empty llm_result_stream_checkpoints" in sql
    assert "ERRCODE = '55000'" in sql
    assert sql.index(no_force) < sql.index("EXISTS (")
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP TABLE")
