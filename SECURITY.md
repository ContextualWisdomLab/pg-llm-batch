# Security Policy

## Supported Versions

The `main` branch receives security fixes. Tagged releases are supported until
their successor is published.

## Reporting a Vulnerability

Please report suspected vulnerabilities through the repository's private
[GitHub Security Advisory form](https://github.com/ContextualWisdomLab/pg-llm-batch/security/advisories/new)
rather than opening a public issue. Include the affected version, reproduction
steps, impact, and any known workaround. Organization-wide handling follows the
[ContextualWisdomLab security policy](https://github.com/ContextualWisdomLab/.github/security/policy).

We acknowledge reports within 3 business days and provide an initial triage
within 7 calendar days. We target a fix or mitigation within 14 days for
confirmed high/critical issues and within 30 days for confirmed medium issues.
We coordinate disclosure with the reporter and normally publish within 90 days;
active exploitation or imminent user harm may require an earlier disclosure.

## Scope

Dependency and filesystem findings are tracked by the organization's central
`osv-scan` and `trivy-fs` gates; fixed-version bumps are applied at the source
(`pyproject.toml` / `uv.lock`), never suppressed.
