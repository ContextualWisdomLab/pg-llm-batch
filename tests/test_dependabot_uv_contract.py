# SPDX-License-Identifier: Apache-2.0
"""Supply-chain contract for Dependabot-managed uv lock updates."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _assert_dependabot_version_updates_stopped(root: Path = ROOT) -> None:
    """Repository-managed Dependabot version updates stay intentionally absent."""
    for relative in (Path(".github/dependabot.yml"), Path(".github/dependabot.yaml")):
        candidate = root / relative
        if candidate.exists() or candidate.is_symlink():
            raise AssertionError(
                f"Dependabot version updates must remain stopped; remove {relative}"
            )


def test_uv_lock_inputs_remain_present_while_dependabot_is_stopped() -> None:
    """Local uv lock integrity stays protected without repo Dependabot config."""
    _assert_dependabot_version_updates_stopped()
    assert (ROOT / "pyproject.toml").is_file()
    assert (ROOT / "uv.lock").is_file()


def test_dependabot_stop_policy_accepts_absence_and_rejects_reappearance():
    """Both recognized config extensions must reject even empty/comment files."""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        root = Path(directory)
        _assert_dependabot_version_updates_stopped(root)
        (root / ".github").mkdir()
        _assert_dependabot_version_updates_stopped(root)
        for extension in ("yml", "yaml"):
            config = root / ".github" / f"dependabot.{extension}"
            for content in ("", "# stopped version updates\n", "version: 2\nupdates: []\n"):
                config.write_text(content, encoding="utf-8")
                try:
                    _assert_dependabot_version_updates_stopped(root)
                except AssertionError as error:
                    assert "Dependabot version updates must remain stopped" in str(error)
                else:
                    raise AssertionError(f"restored {config.name} was accepted")
                finally:
                    config.unlink()
            config.symlink_to(root / "missing-target")
            try:
                _assert_dependabot_version_updates_stopped(root)
            except AssertionError:
                pass
            else:
                raise AssertionError("dangling config symlink was accepted")
            finally:
                config.unlink()
        _assert_dependabot_version_updates_stopped(root)
