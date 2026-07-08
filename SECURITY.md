# Security Policy

## Supported Versions

The `main` branch receives security fixes. Tagged releases are supported until
their successor is published.

## Reporting a Vulnerability

Please report suspected vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the repository **Security** tab) rather than opening
a public issue. Include affected version, reproduction steps, and impact.

We aim to acknowledge reports within 3 business days and to ship a fix or
mitigation for confirmed high/critical issues as quickly as practical.

## Scope

Dependency and filesystem findings are tracked by the organization's central
`osv-scan` and `trivy-fs` gates; fixed-version bumps are applied at the source
(`pyproject.toml` / `uv.lock`), never suppressed.
