"""Prove the installed pg8000 loader rejects import-path shadowing pre-execution.

CI runs this script outside the checkout in isolated Python environments that
contain the built pg-llm-batch wheel plus the exact admitted pg8000 closure. The
shadow package deliberately has no distribution metadata, so the real installed
distribution remains discoverable while Python's import path resolves the
package name to different bytes. The loader must reject that split authority
before the shadow package initializer executes.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from pg_llm_batch.pg8000_driver_adapter import Pg8000DriverAdapter, load_pg8000_driver


def _assert_shadow_package_rejected_before_execution() -> None:
    """Reject a higher-priority package path without executing its initializer."""
    with tempfile.TemporaryDirectory(prefix="pg8000-shadow-") as directory:
        shadow_root = Path(directory)
        package_root = shadow_root / "pg8000"
        package_root.mkdir()
        marker = shadow_root / "shadow-executed"
        package_root.joinpath("__init__.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
            "raise RuntimeError('shadow package executed')\n",
            encoding="utf-8",
        )

        environment = dict(os.environ)
        previous_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(shadow_root)
            if not previous_pythonpath
            else str(shadow_root) + os.pathsep + previous_pythonpath
        )
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from pg_llm_batch.pg8000_driver_adapter import "
                    "Pg8000DriverUnavailableError, load_pg8000_driver\n"
                    "try:\n"
                    "    load_pg8000_driver()\n"
                    "except Pg8000DriverUnavailableError as exc:\n"
                    "    assert str(exc) == 'PostgreSQL driver origin is not admitted'\n"
                    "else:\n"
                    "    raise AssertionError('shadow package was admitted')\n"
                ),
            ],
            env=environment,
            cwd=shadow_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            raise AssertionError("shadow-origin probe did not fail closed")
        if marker.exists():
            raise AssertionError("shadow package initializer executed before rejection")


def main() -> int:
    """Run shadow rejection first, then prove the installed admitted path loads."""
    _assert_shadow_package_rejected_before_execution()
    driver = load_pg8000_driver()
    if not isinstance(driver, Pg8000DriverAdapter):
        raise AssertionError("admitted installed driver did not load")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
