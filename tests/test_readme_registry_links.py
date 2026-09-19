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


def test_packaged_readme_does_not_overstate_secret_storage_encryption() -> None:
    """Keep public SecretStore claims aligned with the optional Fernet boundary."""

    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "KV config + encrypted-secret store" not in readme
    assert "| KV config + secret store | `pg_llm_batch/config.py` |" in readme
    assert "SecretStore` encrypts values only when a Fernet key is supplied" in readme
    assert "base64-obfuscates values unless the store is configured with `require_encryption=True`" in readme


def test_packaged_readme_distinguishes_public_healthz_from_operator_cli_diagnostics() -> None:
    """Keep the README explicit about the unresolved CLI health disclosure boundary."""

    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "fixed required component names and boolean readiness" in readme
    assert "operator-facing diagnostic surface" in readme
    assert "untrusted logs" in readme
    assert "https://github.com/ContextualWisdomLab/pg-llm-batch/issues/203" in readme


def test_packaged_readme_distinguishes_fresh_init_from_existing_volume_extension_retirement() -> None:
    """Do not promote fresh-install cron/http retirement into upgraded-volume truth."""

    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "Fresh initialization no longer creates the former `pg_cron` + `http` provider retriever" in readme
    assert "Existing volumes can still contain those extensions" in readme
    assert "preservation-first retirement migration" in readme
    assert "https://github.com/ContextualWisdomLab/pg-llm-batch/issues/103" in readme
