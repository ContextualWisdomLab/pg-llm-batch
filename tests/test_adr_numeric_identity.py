# SPDX-License-Identifier: Apache-2.0
"""Prevent colliding numeric ADR prefixes across the repository."""

from __future__ import annotations

import re
from pathlib import Path


_ADR_NAME = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md\Z")
_ADR_HEADING = re.compile(r"^# ADR (\d{4}): ", re.MULTILINE)


def test_adr_numeric_prefixes_are_unique_and_match_headings() -> None:
    """Open recovery writers must allocate the next free four-digit prefix."""
    records: list[tuple[str, str]] = []
    for path in sorted(Path("docs/adr").glob("*.md")):
        if path.name == "README.md":
            continue
        name_match = _ADR_NAME.fullmatch(path.name)
        assert name_match is not None, (
            f"{path.name} must be NNNN-kebab-case.md with a unique numeric prefix"
        )
        heading_match = _ADR_HEADING.search(path.read_text(encoding="utf-8"))
        assert heading_match is not None, f"{path.name} must start with '# ADR NNNN: '"
        assert name_match.group(1) == heading_match.group(1), (
            f"{path.name} prefix must match its heading ADR number"
        )
        records.append((name_match.group(1), path.name))

    prefixes = [prefix for prefix, _name in records]
    assert prefixes, "the repository must keep numbered ADRs"
    duplicates = sorted({prefix for prefix in prefixes if prefixes.count(prefix) > 1})
    assert duplicates == [], f"duplicate ADR numeric prefixes: {duplicates}"
