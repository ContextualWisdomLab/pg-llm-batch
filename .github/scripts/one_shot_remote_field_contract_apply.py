# SPDX-License-Identifier: Apache-2.0
"""Apply durable remote-field code changes and robust documentation edits."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_preparer() -> ModuleType:
    """Load the companion one-shot module without requiring a package import."""
    path = Path(".github/scripts/one_shot_remote_field_contract.py")
    spec = importlib.util.spec_from_file_location("remote_field_contract", path)
    if spec is None or spec.loader is None:
        raise SystemExit("unable to load remote field contract preparer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update_docs() -> None:
    """Update operator and release documentation using stable local anchors."""
    docs_path = Path("docs/remote-batch-lifecycle.md")
    docs = docs_path.read_text(encoding="utf-8")
    old_contract = (
        "Caller-provided batch identifiers are validated before reservation.\n"
        "Provider-returned batch identifiers are validated before any lifecycle recorder\n"
        "receives them. These application checks align with the PostgreSQL storage\n"
        "constraints and prevent avoidable remote-success/local-persistence split-brain\n"
        "failures.\n"
    )
    new_contract = (
        "Caller-provided batch identifiers are validated before reservation.\n"
        "Provider-returned batch identifiers and every present input, output, or error\n"
        "file identifier are validated before any lifecycle recorder or PostgreSQL write\n"
        "receives them. The lifecycle table repeats the same identifier syntax as database\n"
        "`CHECK` constraints. NUL-bearing optional endpoint text is discarded and a\n"
        "NUL-bearing status becomes `unknown`, because PostgreSQL text values cannot store\n"
        "the code-zero character. These boundaries prevent avoidable\n"
        "remote-success/local-persistence split-brain failures.\n"
    )
    if old_contract in docs:
        docs = docs.replace(old_contract, new_contract, 1)
    elif new_contract not in docs:
        raise SystemExit("operator identifier contract anchor was not found")

    if "*Character types*" not in docs:
        reference_anchor = (
            "\nPostgreSQL Global Development Group. (2026). "
            "*Conditional expressions*."
        )
        reference = (
            "\nPostgreSQL Global Development Group. (2026). *Character types*. "
            "In\n*PostgreSQL 18 documentation*.\n"
            "https://www.postgresql.org/docs/current/datatype-character.html\n"
        )
        if reference_anchor not in docs:
            raise SystemExit("APA reference insertion anchor was not found")
        docs = docs.replace(reference_anchor, reference + reference_anchor, 1)
    docs_path.write_text(docs, encoding="utf-8")

    changelog_path = Path("CHANGELOG.md")
    changelog = changelog_path.read_text(encoding="utf-8")
    old_entry = (
        "- Enforced NUL-free, 128-character endpoint aliases and 256-character remote\n"
        "  resource identifiers before order reservation, credential resolution,\n"
        "  provider calls, custom lifecycle recorders, or PostgreSQL writes.\n"
    )
    new_entry = (
        "- Enforced NUL-free, 128-character endpoint aliases and 256-character remote\n"
        "  batch, input, output, and error file identifiers before order reservation,\n"
        "  credential resolution, provider calls, custom lifecycle recorders, or\n"
        "  PostgreSQL writes; NUL-bearing optional provider text is normalized safely.\n"
    )
    if old_entry in changelog:
        changelog = changelog.replace(old_entry, new_entry, 1)
    elif new_entry not in changelog:
        raise SystemExit("changelog remote field contract anchor was not found")
    changelog_path.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Apply the code boundary first, then align documentation and citations."""
    preparer = load_preparer()
    preparer.apply_code()
    update_docs()


if __name__ == "__main__":
    main()
