# SPDX-License-Identifier: Apache-2.0
"""Reject duplicate ADR numeric prefixes in the integrated tree."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"
_PREFIX_RE = re.compile(r"^(\d{4})-.+\.md$")


def test_adr_numeric_prefixes_are_unique_in_the_integrated_tree() -> None:
    """Two decisions must not share one NNNN prefix after merge."""
    names_by_prefix: dict[str, list[str]] = defaultdict(list)
    for path in sorted(ADR_DIR.glob("*.md")):
        match = _PREFIX_RE.fullmatch(path.name)
        if match is None:
            continue
        names_by_prefix[match.group(1)].append(path.name)

    duplicates = {
        prefix: names
        for prefix, names in names_by_prefix.items()
        if len(names) > 1
    }
    assert duplicates == {}, duplicates
