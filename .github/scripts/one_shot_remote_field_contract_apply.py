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


def preserve_optional_value_compatibility() -> None:
    """Keep non-string optional provider fields on the existing safe-default path."""
    path = Path("pg_llm_batch/db.py")
    source = path.read_text(encoding="utf-8")
    old = '''def validate_optional_remote_resource_id(
    value: Any,
    field: str,
) -> Optional[str]:
    """Validate a present optional provider identifier or preserve absence.

    ``None`` and the empty string represent an omitted optional Batch object
    field. Every other value must satisfy the same bounded ASCII path-segment
    contract as required remote batch identifiers.
    """
    if value is None or value == "":
        return None
    return validate_remote_resource_id(value, field)
'''
    new = '''def validate_optional_remote_resource_id(
    value: Any,
    field: str,
) -> Optional[str]:
    """Normalize non-string absence and validate every present string identifier.

    Non-string values and the empty string retain the existing deterministic
    safe-default behavior for optional provider fields. Every non-empty string
    must satisfy the bounded ASCII path-segment contract used by required
    remote batch identifiers.
    """
    if not isinstance(value, str) or not value:
        return None
    return validate_remote_resource_id(value, field)
'''
    if source.count(old) != 1:
        raise SystemExit("optional identifier compatibility anchor was not found")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


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
        "Provider-returned batch identifiers and every present string input, output, or\n"
        "error file identifier are validated before any lifecycle recorder or PostgreSQL\n"
        "write receives them. Non-string optional values retain the deterministic absent\n"
        "default. The lifecycle table repeats the same identifier syntax as database\n"
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
        "  batch, input, output, and error file string identifiers before order\n"
        "  reservation, credential resolution, provider calls, custom lifecycle\n"
        "  recorders, or PostgreSQL writes; unsafe optional text is normalized safely.\n"
    )
    if old_entry in changelog:
        changelog = changelog.replace(old_entry, new_entry, 1)
    elif new_entry not in changelog:
        raise SystemExit("changelog remote field contract anchor was not found")
    changelog_path.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Apply the code boundary, compatibility rule, and referenced documentation."""
    preparer = load_preparer()
    preparer.apply_code()
    preserve_optional_value_compatibility()
    update_docs()


if __name__ == "__main__":
    main()
