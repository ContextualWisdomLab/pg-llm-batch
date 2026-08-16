# Workflow registry audit doctoring

## Purpose

This record tells an operator how to detect GitHub Actions identities that are
active in a repository registry but absent from an exact protected source tree,
without disabling, editing, rerunning, or recreating any workflow.

Use the installed command after `pip install pg-llm-batch` or an editable
checkout. Do not treat a missing checkout-root module as the supported
interface. The detector follows NIST SP 800-218 and SLSA v1.0 by binding the
receipt to an exact source commit before any operator reviews a candidate.

```bash
export GITHUB_TOKEN="$(gh auth token)"   # contents:read + actions:read is enough
pg-llm-batch-workflow-audit \
  --repository ContextualWisdomLab/pg-llm-batch \
  --protected-ref main \
  --protected-sha "$(git rev-parse origin/main)"
```

Equivalent module form:

```bash
python -m pg_llm_batch.workflow_registry_audit \
  --repository ContextualWisdomLab/pg-llm-batch \
  --protected-ref main \
  --protected-sha "$(git rev-parse origin/main)"
```

## What to do with the result

- Exit `0`: the live protected ref still matches the supplied SHA, the registry
  was stable across a complete pagination pass, and no active
  repository-backed identity is missing from that exact tree. Keep operating.
- Exit `2`: stdout is a JSON receipt whose `active_absent_workflows` lists
  candidates only. Open a separate operator review. Do not disable those
  workflows from this tool.
- Exit `1`: the audit failed closed. Read the single stderr line, then correct
  the repository selector, SHA, ref, token scope, rate-limit budget, or
  truncated-tree condition and run the same command again.

GitHub-managed `dynamic/` identities appear in `workflow_records` with
`source_kind=platform_dynamic` and `source_present=null`. They are never
orphans. Do not delete platform-managed identities because they lack a
`.github/workflows/` blob.

The library function `audit_repository_workflows` can classify one exact SHA
without live-ref pre/post checks. The CLI always uses
`audit_live_protected_ref_workflows` so a moving protected branch cannot
certify a stale head.

If a library caller supplies `captured_at`, pass one exact built-in string in
the canonical UTC RFC 3339 shape `YYYY-MM-DDTHH:MM:SSZ` with a real calendar
instant. Empty strings, offsets such as `+00:00`, fractional seconds, lowercase
`z`, invalid dates, and oversized values fail before any GitHub read. Omit the
argument to let the auditor write the clock instant. See ADR 0021.

## Trust and security boundary

The client sends path-only GET requests to the fixed origin
`https://api.github.com`, disables redirects, and uses the default TLS
verifier. It never retries automatically. Non-success bodies are not read.
Rate-limit evidence is limited to HTTP 429 or HTTP 403 plus
`X-RateLimit-Remaining: 0` or `Retry-After`.

JSON objects, arrays, strings, integers, and booleans are accepted only as
exact decoder built-in types. Identity members (`ref`, commit `sha`, tree
`sha`) are type-checked before equality. A hostile subclass cannot certify the
caller SHA while resolving a different tree.

`GITHUB_TOKEN` is used only as an `Authorization` header. It is never copied
into stdout, stderr, receipts, or exception cause chains.

This tool does not select tenant scope, touch PostgreSQL, or mutate Actions
state. It is a read-only control-plane detector for this repository and for
hosts that embed `pg-llm-batch` as a module.

## Recovery and rollback

No schema, secret, or workflow mutation is performed. Recovery is to rerun the
same read after correcting the failed input or GitHub condition. Rollback is
removing the console script, package module, ADR, and this record. Reintroducing
workflow disable/enable from this tool is not a routine rollback step.

## Verification

Permanent regression coverage requires that:

- hostile `str` subclasses cannot satisfy commit, tree, or ref identity by
  lying about equality;
- raising identity subclasses become `WorkflowRegistryAuditError` without
  leaking custom exception text;
- `dynamic/` identities are receipted and never orphaned;
- unknown workflow states fail closed;
- multi-page registries are accepted only after a second identical pass;
- truncated trees, moving protected refs, and oversize responses fail closed;
- the console script `pg-llm-batch-workflow-audit` is declared in package
  metadata; and
- README, architecture, ADR 0021, changelog, and this doctoring record all tell
  the operator to review candidates instead of disabling workflows; and
- caller-supplied receipt timestamps are rejected unless they are finite
  canonical UTC RFC 3339 values.

## References

GitHub. (n.d.). *REST API endpoints for GitHub Actions workflows*. GitHub Docs.
Retrieved August 16, 2026, from
https://docs.github.com/en/rest/actions/workflows

GitHub. (n.d.). *REST API endpoints for Git commits*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/rest/git/commits

GitHub. (n.d.). *REST API endpoints for Git trees*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/rest/git/trees

GitHub. (n.d.). *REST API endpoints for Git references*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/rest/git/refs

GitHub. (n.d.). *Rate limits for the REST API*. GitHub Docs. Retrieved August
16, 2026, from
https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

Klyne, G., & Newman, C. (2002). *Date and time on the internet: Timestamps*
(RFC 3339). https://doi.org/10.17487/RFC3339

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

The Linux Foundation. (2023). *Supply-chain Levels for Software Artifacts
(SLSA) v1.0*. https://slsa.dev/spec/v1.0/

Torres-Arias, S., Afzali, H., Kuppusamy, T. K., Curtmola, R., & Cappos, J.
(2019). in-toto: Providing farm-to-table guarantees for bits and bytes. In
*Proceedings of the 28th USENIX Security Symposium* (pp. 1393–1410). USENIX
Association. https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias
