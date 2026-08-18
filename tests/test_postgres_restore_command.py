# SPDX-License-Identifier: Apache-2.0
"""Contracts for bounded PostgreSQL archive-recovery command binding."""

from __future__ import annotations

import pytest

from pg_llm_batch.postgres_restore_command import (
    PostgresArchiveRestoreCommand,
    PostgresRestoreCommandError,
    bind_postgres_archive_restore_command,
)


def test_binder_emits_fixed_postgresql_restore_placeholders() -> None:
    """Bind one absolute helper token to PostgreSQL's exact file/destination placeholders."""
    command = bind_postgres_archive_restore_command(
        "/usr/local/libexec/pg-llm-batch-restore-wal"
    )

    assert command.helper_executable == "/usr/local/libexec/pg-llm-batch-restore-wal"
    assert command.server_setting() == (
        "restore_command",
        "/usr/local/libexec/pg-llm-batch-restore-wal %f %p",
    )


def test_direct_canonical_construction_is_equivalent() -> None:
    """Direct evidence construction accepts only the same canonical helper token."""
    command = PostgresArchiveRestoreCommand(
        helper_executable="/opt/pg-llm-batch/bin/restore-wal"
    )

    assert command.server_setting()[1].endswith(" %f %p")


@pytest.mark.parametrize(
    "helper_executable",
    [
        "restore-wal",
        "./restore-wal",
        "/",
        "/opt/../bin/restore-wal",
        "/opt/./bin/restore-wal",
        "/opt//bin/restore-wal",
        "/opt/bin/",
        "/opt/bin/restore wal",
        "/opt/bin/restore;true",
        "/opt/bin/restore&&true",
        "/opt/bin/restore|true",
        "/opt/bin/restore$(id)",
        "/opt/bin/restore`id`",
        "/opt/bin/restore%f",
        "/opt/bin/restore%p",
        "/opt/bin/restore'quoted",
        '/opt/bin/restore"quoted',
        "/opt/bin/restore\\quoted",
        "/opt/bin/restore\nwal",
        "/opt/bin/한글",
        "/" + "a" * 512,
        "",
    ],
)
def test_noncanonical_or_shell_active_helper_paths_fail_closed(
    helper_executable: str,
) -> None:
    """Reject relative, ambiguous, unbounded, non-ASCII, and shell-active helper tokens."""
    with pytest.raises(
        PostgresRestoreCommandError,
        match="^invalid PostgreSQL restore helper executable$",
    ):
        bind_postgres_archive_restore_command(helper_executable)


def test_exact_string_type_is_required_before_behavior_bearing_operations() -> None:
    """Reject string subclasses before comparison, encoding, or rendering hooks can run."""

    class HostileString(str):
        def __eq__(self, other: object) -> bool:
            raise AssertionError("must not compare hostile helper authority")

        def __str__(self) -> str:
            raise AssertionError("must not render hostile helper authority")

        def encode(self, *args: object, **kwargs: object) -> bytes:
            raise AssertionError("must not encode hostile helper authority")

    with pytest.raises(
        PostgresRestoreCommandError,
        match="^invalid PostgreSQL restore helper executable$",
    ):
        bind_postgres_archive_restore_command(
            HostileString("/usr/local/libexec/pg-llm-batch-restore-wal")
        )


def test_non_string_helper_authority_fails_closed() -> None:
    """Reject non-string helper authority with one fixed content-free diagnostic."""
    with pytest.raises(
        PostgresRestoreCommandError,
        match="^invalid PostgreSQL restore helper executable$",
    ):
        bind_postgres_archive_restore_command(object())  # type: ignore[arg-type]


def test_direct_construction_cannot_inject_a_free_form_restore_command() -> None:
    """The evidence object never accepts caller-supplied arguments or placeholder order."""
    with pytest.raises(TypeError):
        PostgresArchiveRestoreCommand(  # type: ignore[call-arg]
            helper_executable="/opt/pg-llm-batch/bin/restore-wal",
            restore_command="/bin/sh -c 'cat /tmp/archive/%f > %p'",
        )


def test_mutated_bound_helper_is_revalidated_before_server_setting() -> None:
    """Do not let post-construction dataclass mutation bypass shell-token validation."""
    command = bind_postgres_archive_restore_command(
        "/usr/local/libexec/pg-llm-batch-restore-wal"
    )
    object.__setattr__(command, "helper_executable", "/bin/restore;true")

    with pytest.raises(
        PostgresRestoreCommandError,
        match="^invalid PostgreSQL restore helper executable$",
    ):
        command.server_setting()


def test_setting_contains_no_archive_path_or_credentials() -> None:
    """The bounded setting carries only reviewed executable authority and server placeholders."""
    value = bind_postgres_archive_restore_command(
        "/usr/libexec/pg-llm-batch/restore-wal"
    ).server_setting()[1]

    assert "archive" not in value
    assert "password" not in value
    assert "secret" not in value
    assert value.count("%f") == 1
    assert value.count("%p") == 1
