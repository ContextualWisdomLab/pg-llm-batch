"""Regression contract for registry-safe public README links."""

from pathlib import Path
import re


_REPOSITORY_RELATIVE_TARGET = re.compile(
    r"\]\((?:docs/[^)]+|LICENSE|NOTICE)\)"
)

_REQUIRED_PUBLIC_LINKS = (
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/NOTICE",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/remote-batch-lifecycle.md",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/doctoring/tenant-scoped-lifecycle.md",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/doctoring/bootstrap-dsn-precedence.md",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/doctoring/cli-secret-input.md",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/doctoring/count-tokens-stdin-privacy.md",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/doctoring/legacy-pgsql-http-retrieval.md",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/docs/doctoring/opentelemetry-operations.md",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/tree/main/docs/papers/",
    "https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/LICENSE",
)


def test_packaged_readme_keeps_repository_links_registry_safe_and_discoverable() -> None:
    """Require absolute package-registry links without dropping public operator docs."""

    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert _REPOSITORY_RELATIVE_TARGET.search(readme) is None
    for url in _REQUIRED_PUBLIC_LINKS:
        assert url in readme
