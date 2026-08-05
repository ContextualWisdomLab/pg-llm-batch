# Standalone Lifecycle Compatibility Evidence

- RED workflow source head: `5ce36a0b576d717fcf7b524eed7c09869551ca1d`.
- Verified product-change commit: `6493bd3f1674407a93578d19b14f70b3692f98c7`.
- The legacy persistence helper no longer exposes the internal
  `tenant_scope` field, while its transaction still binds the exact
  `standalone` scope for forced row-level security.
- The explicit tenant-aware helper retains tenant-qualified results.
- Documentation tests collapse insignificant Markdown whitespace and
  enforce the current-state, arbitrary-SQL, role, and trusted-boundary
  limitations.
- Focused contracts, the complete non-integration suite, 100%
  production statement/branch/docstring coverage, Ruff, compilation,
  lock freshness, distributions, Compose validation, and both
  container builds passed before publication.
- The temporary write-capable workflow removed itself from the final tree.
- Repository CI, security, review, and branch-protection evidence must still
  be established on the exact current pull-request head; no predecessor-head
  result is accepted as merge evidence.
