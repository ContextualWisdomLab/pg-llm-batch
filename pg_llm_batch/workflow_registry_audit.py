# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Read-only GitHub Actions registry audit for protected-source drift.

The tool intentionally performs no workflow mutation. It binds one audit receipt to
an exact protected commit, reads the repository Actions registry with complete
pagination, and reports active repository-backed workflow identities whose exact
source path is absent from that protected tree. GitHub-managed ``dynamic/``
identities remain receipted separately and are never treated as deleted-YAML
candidates. All reported candidates still require separate operator review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import quote

import aiohttp

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_PROTECTED_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_API_PATH_RE = re.compile(r"^/(?!/)[^\r\n]*$")
_WORKFLOW_PREFIX = ".github/workflows/"
_DYNAMIC_WORKFLOW_PREFIX = "dynamic/"
_WORKFLOW_STATES = frozenset(
    {
        "active",
        "deleted",
        "disabled_fork",
        "disabled_inactivity",
        "disabled_manually",
    }
)
_GITHUB_API_URL = "https://api.github.com"
_DEFAULT_TIMEOUT_SECONDS = 15.0
_PAGE_SIZE = 100
_MAX_REGISTRY_WORKFLOWS = 10_000
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 64 * 1024


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
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise WorkflowRegistryAuditError("GitHub audit timeout must be positive finite")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> dict[str, object]:
        """Read one path-only GitHub API object over a fixed verified-TLS origin."""
        if not _API_PATH_RE.fullmatch(path):
            raise WorkflowRegistryAuditError("GitHub API path is invalid")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise WorkflowRegistryAuditError(
                "GitHub workflow audit sync client cannot run inside an active event loop"
            )
        return asyncio.run(self._get_json(path))

    async def _get_json(self, path: str) -> dict[str, object]:
        """Perform one fixed-origin aiohttp GET with redirects and body growth bounded."""
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        try:
            async with aiohttp.ClientSession(
                base_url=_GITHUB_API_URL,
                headers=self._headers(),
                timeout=timeout,
            ) as session:
                async with session.get(path, allow_redirects=False) as response:
                    if response.status // 100 != 2:
                        remaining = response.headers.get("X-RateLimit-Remaining")
                        retry_after = response.headers.get("Retry-After")
                        if response.status == 429 or (
                            response.status == 403
                            and (remaining == "0" or retry_after is not None)
                        ):
                            raise WorkflowRegistryAuditError(
                                "GitHub workflow audit rate limited"
                            )
                        raise WorkflowRegistryAuditError(
                            "GitHub workflow audit read failed"
                        )
                    raw = await self._read_bounded_response(response)
            payload = json.loads(raw.decode("utf-8"))
        except WorkflowRegistryAuditError:
            raise
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ):
            raise WorkflowRegistryAuditError("GitHub workflow audit read failed") from None
        if type(payload) is not dict:
            raise WorkflowRegistryAuditError("GitHub workflow audit response is invalid")
        return payload

    async def _read_bounded_response(self, response: object) -> bytes:
        """Stream one decoded HTTP body while enforcing a fixed memory budget.

        GitHub documents a 7 MB recursive-tree response ceiling. The 16 MiB
        budget deliberately leaves protocol/envelope headroom while preventing
        a malformed or unexpectedly large authenticated response from being
        materialized without bound. The limit is also enforced for chunked
        responses that omit ``Content-Length``.
        """
        declared_value = getattr(response, "content_length", None)
        declared_bytes = (
            declared_value
            if type(declared_value) is int and declared_value >= 0
            else None
        )
        if declared_bytes is not None and declared_bytes > _MAX_RESPONSE_BYTES:
            raise WorkflowRegistryAuditError(
                "GitHub workflow audit response exceeded byte limit"
            )

        stream = getattr(response, "content", None)
        iterator = getattr(stream, "iter_chunked", None)
        if not callable(iterator):
            raise WorkflowRegistryAuditError(
                "GitHub workflow audit response stream is invalid"
            )

        payload = bytearray()
        async for chunk in iterator(_RESPONSE_CHUNK_BYTES):
            if isinstance(chunk, memoryview):
                chunk_bytes = chunk.tobytes()
            elif isinstance(chunk, (bytes, bytearray)):
                chunk_bytes = bytes(chunk)
            else:
                raise WorkflowRegistryAuditError(
                    "GitHub workflow audit response stream is invalid"
                )
            if len(payload) + len(chunk_bytes) > _MAX_RESPONSE_BYTES:
                raise WorkflowRegistryAuditError(
                    "GitHub workflow audit response exceeded byte limit"
                )
            payload.extend(chunk_bytes)
        return bytes(payload)

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


def audit_live_protected_ref_workflows(
    *,
    repository_full_name: str,
    protected_ref: str,
    expected_protected_sha: str,
    client: _JsonClient,
    captured_at: str | None = None,
) -> dict[str, object]:
    """Audit one live protected branch while proving its exact SHA stays unchanged.

    The caller supplies the independently resolved expected protected SHA. The
    function verifies the live branch immediately before and after the exact-SHA
    tree/registry audit. Any mismatch or observed movement invalidates the whole
    receipt instead of silently certifying a stale protected head.
    """
    _validate_captured_at(captured_at)
    _validate_repository(repository_full_name)
    _validate_protected_ref(protected_ref)
    _validate_protected_sha(expected_protected_sha)
    normalized_sha = expected_protected_sha.lower()

    initial_sha = _read_protected_ref_sha(
        repository_full_name=repository_full_name,
        protected_ref=protected_ref,
        client=client,
    )
    if initial_sha != normalized_sha:
        raise WorkflowRegistryAuditError("protected ref does not match expected SHA")

    receipt = audit_repository_workflows(
        repository_full_name=repository_full_name,
        protected_sha=normalized_sha,
        client=client,
        captured_at=captured_at,
    )

    final_sha = _read_protected_ref_sha(
        repository_full_name=repository_full_name,
        protected_ref=protected_ref,
        client=client,
    )
    if final_sha != normalized_sha:
        raise WorkflowRegistryAuditError("protected ref moved during audit")

    receipt["protected_ref"] = protected_ref
    return receipt


def audit_repository_workflows(
    *,
    repository_full_name: str,
    protected_sha: str,
    client: _JsonClient,
    captured_at: str | None = None,
) -> dict[str, object]:
    """Return an exact-SHA read-only registry/source classification receipt.

    Active repository-backed identities absent from the exact protected tree are
    reported as candidates only. GitHub-managed dynamic identities are retained
    in the receipt with indeterminate protected-source presence and never become
    orphan candidates. The caller must separately prove whether any candidate has
    a legitimate platform role before future workflow-state mutation. Use
    :func:`audit_live_protected_ref_workflows` when live-ref movement must also
    invalidate the receipt.
    """
    _validate_captured_at(captured_at)
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
        path = str(record["path"])
        source_kind = (
            "repository" if path.startswith(_WORKFLOW_PREFIX) else "platform_dynamic"
        )
        source_present: bool | None = (
            path in protected_paths if source_kind == "repository" else None
        )
        classified = {
            "workflow_id": record["workflow_id"],
            "path": path,
            "state": record["state"],
            "source_kind": source_kind,
            "source_present": source_present,
        }
        classified_records.append(classified)
        if (
            record["state"] == "active"
            and source_kind == "repository"
            and source_present is False
        ):
            active_absent.append(
                {
                    "workflow_id": record["workflow_id"],
                    "path": path,
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


def _read_protected_ref_sha(
    *,
    repository_full_name: str,
    protected_ref: str,
    client: _JsonClient,
) -> str:
    """Resolve an exact protected branch head SHA from bounded GitHub metadata."""
    encoded_ref = quote(protected_ref, safe="/")
    payload = client.get_json(
        f"/repos/{repository_full_name}/git/ref/heads/{encoded_ref}"
    )
    if type(payload) is not dict:
        raise WorkflowRegistryAuditError("protected ref response is invalid")
    ref_name = payload.get("ref")
    expected_ref = f"refs/heads/{protected_ref}"
    if type(ref_name) is not str or ref_name != expected_ref:
        raise WorkflowRegistryAuditError("protected ref response is invalid")
    ref_object = payload.get("object")
    if type(ref_object) is not dict:
        raise WorkflowRegistryAuditError("protected ref response is invalid")
    sha = ref_object.get("sha")
    object_type = ref_object.get("type")
    if (
        type(sha) is not str
        or not _SHA_RE.fullmatch(sha)
        or type(object_type) is not str
        or object_type != "commit"
    ):
        raise WorkflowRegistryAuditError("protected ref response is invalid")
    return sha.lower()


def _read_protected_workflow_paths(
    *,
    repository_full_name: str,
    protected_sha: str,
    client: _JsonClient,
) -> set[str]:
    """Resolve a protected commit to its exact tree and return workflow blob paths."""
    commit_payload = client.get_json(
        f"/repos/{repository_full_name}/git/commits/{protected_sha}"
    )
    if type(commit_payload) is not dict:
        raise WorkflowRegistryAuditError("protected commit response is invalid")
    commit_sha = commit_payload.get("sha")
    if (
        type(commit_sha) is not str
        or not _SHA_RE.fullmatch(commit_sha)
        or commit_sha != protected_sha
    ):
        raise WorkflowRegistryAuditError("protected commit response is invalid")
    commit_tree = commit_payload.get("tree")
    if type(commit_tree) is not dict:
        raise WorkflowRegistryAuditError("protected commit response is invalid")
    tree_sha = commit_tree.get("sha")
    if type(tree_sha) is not str or not _SHA_RE.fullmatch(tree_sha):
        raise WorkflowRegistryAuditError("protected commit response is invalid")
    tree_sha = tree_sha.lower()

    payload = client.get_json(
        f"/repos/{repository_full_name}/git/trees/{tree_sha}?recursive=1"
    )
    if type(payload) is not dict:
        raise WorkflowRegistryAuditError("protected tree SHA does not match commit tree SHA")
    response_sha = payload.get("sha")
    if (
        type(response_sha) is not str
        or not _SHA_RE.fullmatch(response_sha)
        or response_sha != tree_sha
    ):
        raise WorkflowRegistryAuditError("protected tree SHA does not match commit tree SHA")
    if payload.get("truncated") is not False:
        raise WorkflowRegistryAuditError("protected tree is truncated")
    tree = payload.get("tree")
    if type(tree) is not list:
        raise WorkflowRegistryAuditError("protected tree response is invalid")

    paths: set[str] = set()
    for entry in tree:
        if type(entry) is not dict:
            raise WorkflowRegistryAuditError("protected tree response is invalid")
        path = entry.get("path")
        entry_type = entry.get("type")
        if type(path) is not str or type(entry_type) is not str:
            raise WorkflowRegistryAuditError("protected tree response is invalid")
        if entry_type == "blob" and path.startswith(_WORKFLOW_PREFIX):
            paths.add(path)
    return paths


def _read_registry(
    *,
    repository_full_name: str,
    client: _JsonClient,
) -> tuple[list[dict[str, object]], int, int]:
    """Read one coherent workflow registry or fail closed on pagination drift.

    A single multi-page traversal can combine rows from two different registry
    states even when ``total_count`` remains unchanged. Therefore multi-page
    receipts are accepted only when a second complete traversal observes the
    same validated workflow identities, paths, and states. Single-page reads
    already arrive as one response and do not need the extra pass.
    """
    records, pages_scanned, expected_total = _read_registry_pass(
        repository_full_name=repository_full_name,
        client=client,
    )
    if pages_scanned > 1:
        verification_records, verification_pages, verification_total = _read_registry_pass(
            repository_full_name=repository_full_name,
            client=client,
        )
        if (
            verification_total != expected_total
            or verification_pages != pages_scanned
            or _registry_signature(verification_records) != _registry_signature(records)
        ):
            raise WorkflowRegistryAuditError("workflow registry changed during audit")
    return records, pages_scanned, expected_total


def _read_registry_pass(
    *,
    repository_full_name: str,
    client: _JsonClient,
) -> tuple[list[dict[str, object]], int, int]:
    """Read one complete pagination pass while enforcing stable cardinality."""
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
        if type(payload) is not dict:
            raise WorkflowRegistryAuditError("workflow registry response is invalid")
        pages_scanned += 1
        total_count = _require_nonnegative_int(payload.get("total_count"))
        if total_count > _MAX_REGISTRY_WORKFLOWS:
            raise WorkflowRegistryAuditError(
                "workflow registry exceeds supported workflow limit"
            )
        if expected_total is None:
            expected_total = total_count
        elif total_count != expected_total:
            raise WorkflowRegistryAuditError("workflow registry changed during audit")

        workflows = payload.get("workflows")
        if type(workflows) is not list:
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

    return records, pages_scanned, expected_total


def _registry_signature(records: list[dict[str, object]]) -> tuple[tuple[int, str, str], ...]:
    """Return an order-independent identity/path/state signature for one pass."""
    return tuple(
        sorted(
            (
                int(record["workflow_id"]),
                str(record["path"]),
                str(record["state"]),
            )
            for record in records
        )
    )


def _validate_workflow_record(raw_record: object) -> dict[str, object]:
    """Validate exact decoder primitive types for one workflow registry record."""
    if type(raw_record) is not dict:
        raise WorkflowRegistryAuditError("workflow registry record is invalid")
    workflow_id = raw_record.get("id")
    path = raw_record.get("path")
    state = raw_record.get("state")
    if (
        type(workflow_id) is not int
        or workflow_id <= 0
        or type(path) is not str
        or type(state) is not str
        or state not in _WORKFLOW_STATES
    ):
        raise WorkflowRegistryAuditError("workflow registry record is invalid")
    components = path.split("/")
    if (
        "\\" in path
        or any(component in {"", ".", ".."} for component in components)
        or not (
            path.startswith(_WORKFLOW_PREFIX)
            or path.startswith(_DYNAMIC_WORKFLOW_PREFIX)
        )
    ):
        raise WorkflowRegistryAuditError("workflow registry record path is invalid")
    return {"workflow_id": workflow_id, "path": path, "state": state}


def _require_nonnegative_int(value: object) -> int:
    """Require an exact non-negative integer API count."""
    if type(value) is not int or value < 0:
        raise WorkflowRegistryAuditError("workflow registry total count is invalid")
    return value


def _validate_captured_at(captured_at: str | None) -> None:
    """Reject non-string receipt timestamps before any GitHub read."""
    if captured_at is not None and type(captured_at) is not str:
        raise WorkflowRegistryAuditError("captured_at must be an exact timestamp string")


def _validate_repository(repository_full_name: str) -> None:
    """Reject malformed repository selectors before any network read."""
    if type(repository_full_name) is not str:
        raise WorkflowRegistryAuditError("repository must use owner/name syntax")
    components = repository_full_name.split("/")
    if (
        not _REPOSITORY_RE.fullmatch(repository_full_name)
        or any(component in {".", ".."} for component in components)
    ):
        raise WorkflowRegistryAuditError("repository must use owner/name syntax")


def _validate_protected_sha(protected_sha: str) -> None:
    """Require immutable commit identity instead of a branch/ref name."""
    if type(protected_sha) is not str or not _SHA_RE.fullmatch(protected_sha):
        raise WorkflowRegistryAuditError("protected_sha must be an exact 40-hex protected SHA")


def _validate_protected_ref(protected_ref: str) -> None:
    """Reject ambiguous or path-like branch selectors before any network read."""
    if type(protected_ref) is not str:
        raise WorkflowRegistryAuditError("protected_ref must be a safe branch name")
    if (
        not _PROTECTED_REF_RE.fullmatch(protected_ref)
        or protected_ref.startswith("/")
        or protected_ref.endswith("/")
        or "//" in protected_ref
        or "@{" in protected_ref
        or protected_ref.startswith("refs/")
        or protected_ref.startswith("heads/")
        or any(component in {"", ".", ".."} for component in protected_ref.split("/"))
    ):
        raise WorkflowRegistryAuditError("protected_ref must be a safe branch name")


def _utc_timestamp() -> str:
    """Return a UTC RFC 3339 timestamp for the audit receipt."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parser() -> argparse.ArgumentParser:
    """Build the command-line interface for an explicit exact-SHA audit."""
    parser = argparse.ArgumentParser(
        description=(
            "Read a repository Actions registry and classify active workflow identities "
            "whose exact path is absent from a stable protected branch head."
        )
    )
    parser.add_argument("--repository", required=True, help="GitHub owner/name repository")
    parser.add_argument(
        "--protected-sha",
        required=True,
        help="Independently resolved exact 40-hex protected commit SHA",
    )
    parser.add_argument(
        "--protected-ref",
        default="main",
        help="Protected branch to verify before and after the audit (default: main)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help="Finite timeout for each read-only GitHub API request",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the live-ref audit, print JSON, and signal active-absent candidates."""
    args = _parser().parse_args(argv)
    try:
        client = GitHubReadClient(
            token=os.environ.get("GITHUB_TOKEN"),
            timeout_seconds=args.timeout_seconds,
        )
        receipt = audit_live_protected_ref_workflows(
            repository_full_name=args.repository,
            protected_ref=args.protected_ref,
            expected_protected_sha=args.protected_sha,
            client=client,
        )
    except WorkflowRegistryAuditError as exc:
        print(f"workflow_registry_audit: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 2 if receipt["active_absent_workflows"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
