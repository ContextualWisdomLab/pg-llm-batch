"""Read-only GitHub Actions registry audit for protected-source drift.

The tool intentionally performs no workflow mutation. It binds one audit receipt to
an exact protected commit, reads the repository Actions registry with complete
pagination, and reports active workflow identities whose exact source path is
absent from that protected tree. Those records are candidates for separate
operator review, not automatic disable decisions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_WORKFLOW_PREFIX = ".github/workflows/"
_GITHUB_API_URL = "https://api.github.com"
_DEFAULT_TIMEOUT_SECONDS = 15.0
_PAGE_SIZE = 100


class WorkflowRegistryAuditError(RuntimeError):
    """Represent a bounded fail-closed workflow audit failure."""


class _JsonClient(Protocol):
    """Describe the minimal read-only JSON client used by the audit."""

    def get_json(self, path: str) -> dict[str, object]:
        """Return one decoded GitHub API object for ``path``."""


class GitHubReadClient:
    """Perform bounded read-only GitHub API requests without diagnostic leakage."""

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Configure fixed-origin read-only API access with a finite timeout."""
        if timeout_seconds <= 0:
            raise WorkflowRegistryAuditError("GitHub audit timeout must be positive")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> dict[str, object]:
        """Read one JSON object and replace transport/parser failures with fixed evidence."""
        request = Request(
            f"{_GITHUB_API_URL}{path}",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            raise WorkflowRegistryAuditError("GitHub workflow audit read failed") from None
        if not isinstance(payload, dict):
            raise WorkflowRegistryAuditError("GitHub workflow audit response is invalid")
        return payload

    def _headers(self) -> dict[str, str]:
        """Build fixed GitHub headers without exposing the token in output."""
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "pg-llm-batch-workflow-registry-audit/1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


def audit_repository_workflows(
    *,
    repository_full_name: str,
    protected_sha: str,
    client: _JsonClient,
    captured_at: str | None = None,
) -> dict[str, object]:
    """Return an exact-SHA read-only registry/source classification receipt.

    Active identities absent from the exact protected tree are reported as
    candidates only. The caller must separately prove whether a candidate has a
    legitimate platform role before any future workflow-state mutation.
    """
    _validate_repository(repository_full_name)
    _validate_protected_sha(protected_sha)
    normalized_sha = protected_sha.lower()

    protected_paths = _read_protected_workflow_paths(
        repository_full_name=repository_full_name,
        protected_sha=normalized_sha,
        client=client,
    )
    workflow_records, pages_scanned, registry_total_count = _read_registry(
        repository_full_name=repository_full_name,
        client=client,
    )

    classified_records: list[dict[str, object]] = []
    active_absent: list[dict[str, object]] = []
    for record in workflow_records:
        source_present = record["path"] in protected_paths
        classified = {
            "workflow_id": record["workflow_id"],
            "path": record["path"],
            "state": record["state"],
            "source_present": source_present,
        }
        classified_records.append(classified)
        if record["state"] == "active" and not source_present:
            active_absent.append(
                {
                    "workflow_id": record["workflow_id"],
                    "path": record["path"],
                    "state": record["state"],
                }
            )

    active_absent.sort(key=lambda item: (str(item["path"]), int(item["workflow_id"])))
    return {
        "repository_full_name": repository_full_name,
        "protected_sha": normalized_sha,
        "captured_at": captured_at or _utc_timestamp(),
        "pages_scanned": pages_scanned,
        "registry_total_count": registry_total_count,
        "protected_workflow_paths": sorted(protected_paths),
        "workflow_records": classified_records,
        "active_absent_workflows": active_absent,
    }


def _read_protected_workflow_paths(
    *,
    repository_full_name: str,
    protected_sha: str,
    client: _JsonClient,
) -> set[str]:
    """Read exact protected-tree workflow blob paths or fail closed."""
    payload = client.get_json(
        f"/repos/{repository_full_name}/git/trees/{protected_sha}?recursive=1"
    )
    if payload.get("sha") != protected_sha:
        raise WorkflowRegistryAuditError("protected tree SHA does not match requested SHA")
    if payload.get("truncated") is not False:
        raise WorkflowRegistryAuditError("protected tree is truncated")
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise WorkflowRegistryAuditError("protected tree response is invalid")

    paths: set[str] = set()
    for entry in tree:
        if not isinstance(entry, dict):
            raise WorkflowRegistryAuditError("protected tree response is invalid")
        path = entry.get("path")
        entry_type = entry.get("type")
        if not isinstance(path, str) or not isinstance(entry_type, str):
            raise WorkflowRegistryAuditError("protected tree response is invalid")
        if entry_type == "blob" and path.startswith(_WORKFLOW_PREFIX):
            paths.add(path)
    return paths


def _read_registry(
    *,
    repository_full_name: str,
    client: _JsonClient,
) -> tuple[list[dict[str, object]], int, int]:
    """Read the complete stable workflow registry with explicit pagination evidence."""
    expected_total: int | None = None
    page = 1
    pages_scanned = 0
    records: list[dict[str, object]] = []
    seen_ids: set[int] = set()

    while expected_total is None or len(records) < expected_total:
        payload = client.get_json(
            f"/repos/{repository_full_name}/actions/workflows"
            f"?per_page={_PAGE_SIZE}&page={page}"
        )
        pages_scanned += 1
        total_count = _require_nonnegative_int(payload.get("total_count"))
        if expected_total is None:
            expected_total = total_count
        elif total_count != expected_total:
            raise WorkflowRegistryAuditError("workflow registry changed during audit")

        workflows = payload.get("workflows")
        if not isinstance(workflows, list):
            raise WorkflowRegistryAuditError("workflow registry response is invalid")
        if not workflows and len(records) < expected_total:
            raise WorkflowRegistryAuditError("workflow registry pagination is incomplete")

        for raw_record in workflows:
            record = _validate_workflow_record(raw_record)
            workflow_id = int(record["workflow_id"])
            if workflow_id in seen_ids:
                raise WorkflowRegistryAuditError("workflow registry contains duplicate workflow id")
            seen_ids.add(workflow_id)
            records.append(record)

        if len(records) > expected_total:
            raise WorkflowRegistryAuditError("workflow registry changed during audit")
        page += 1

    if expected_total is None:
        raise WorkflowRegistryAuditError("workflow registry response is invalid")
    return records, pages_scanned, expected_total


def _validate_workflow_record(raw_record: object) -> dict[str, object]:
    """Validate only identity/path/state fields needed for safe classification."""
    if not isinstance(raw_record, dict):
        raise WorkflowRegistryAuditError("workflow registry record is invalid")
    workflow_id = raw_record.get("id")
    path = raw_record.get("path")
    state = raw_record.get("state")
    if (
        isinstance(workflow_id, bool)
        or not isinstance(workflow_id, int)
        or workflow_id <= 0
        or not isinstance(path, str)
        or not isinstance(state, str)
        or not state
    ):
        raise WorkflowRegistryAuditError("workflow registry record is invalid")
    if not path.startswith(_WORKFLOW_PREFIX) or "\\" in path or ".." in path.split("/"):
        raise WorkflowRegistryAuditError("workflow registry record path is invalid")
    return {"workflow_id": workflow_id, "path": path, "state": state}


def _require_nonnegative_int(value: object) -> int:
    """Require a non-boolean, non-negative integer API count."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkflowRegistryAuditError("workflow registry total count is invalid")
    return value


def _validate_repository(repository_full_name: str) -> None:
    """Reject malformed repository selectors before any network read."""
    if not _REPOSITORY_RE.fullmatch(repository_full_name):
        raise WorkflowRegistryAuditError("repository must use owner/name syntax")


def _validate_protected_sha(protected_sha: str) -> None:
    """Require immutable commit identity instead of a branch/ref name."""
    if not _SHA_RE.fullmatch(protected_sha):
        raise WorkflowRegistryAuditError("protected_sha must be an exact 40-hex protected SHA")


def _utc_timestamp() -> str:
    """Return a UTC RFC 3339 timestamp for the audit receipt."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parser() -> argparse.ArgumentParser:
    """Build the command-line interface for an explicit exact-SHA audit."""
    parser = argparse.ArgumentParser(
        description=(
            "Read a repository Actions registry and classify active workflow identities "
            "whose exact path is absent from an exact protected commit."
        )
    )
    parser.add_argument("--repository", required=True, help="GitHub owner/name repository")
    parser.add_argument(
        "--protected-sha",
        required=True,
        help="Exact 40-hex protected commit SHA; mutable ref names are rejected",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help="Finite timeout for each read-only GitHub API request",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the audit, print a JSON receipt, and signal active-absent candidates."""
    args = _parser().parse_args(argv)
    try:
        client = GitHubReadClient(
            token=os.environ.get("GITHUB_TOKEN"),
            timeout_seconds=args.timeout_seconds,
        )
        receipt = audit_repository_workflows(
            repository_full_name=args.repository,
            protected_sha=args.protected_sha,
            client=client,
        )
    except WorkflowRegistryAuditError as exc:
        print(f"workflow_registry_audit: {exc}", file=os.sys.stderr)
        return 1

    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 2 if receipt["active_absent_workflows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
