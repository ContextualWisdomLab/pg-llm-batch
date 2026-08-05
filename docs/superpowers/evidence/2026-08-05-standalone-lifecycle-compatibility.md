# Standalone Lifecycle Compatibility Evidence

- RED workflow source head: `5ce36a0b576d717fcf7b524eed7c09869551ca1d`.
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
  container builds passed.
- This temporary write-capable workflow removed itself from the final tree.
