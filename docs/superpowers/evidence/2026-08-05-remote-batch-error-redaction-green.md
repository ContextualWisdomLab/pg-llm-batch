# Remote batch recovery redaction — GREEN evidence

## Verified implementation head

`9ee12b179ac944259a41bf247614c55303dfbb54`

Base SHA:

`3dbd37a372cd5f1898dab6f0096a7ed0e001493e`

## Exact-head hosted verification

The implementation head passed all repository-owned exact-head workflows:

- CI run `30977537772`;
- SAST Semgrep run `30977537826`; and
- Security Scan run `30977537858`.

The CI matrix and quality jobs established:

- Python 3.10 unit tests: success;
- Python 3.12 unit tests: success;
- Python 3.14 unit tests: success;
- component and PostgreSQL container builds: success;
- Ruff: `All checks passed!`;
- public docstring coverage: `100.0%`;
- production statement coverage: `1350/1350` (`100%`);
- production branch coverage: `370/370` (`100%`);
- `pg_llm_batch/durable_client.py`: 69 statements and 10 branches with no
  misses or partial branches;
- complete non-integration result: `305 passed, 3 deselected`;
- lockfile freshness: success; and
- source distribution and wheel builds: success.

## Contract proven

The deterministic security regression proves that an unsupported
provider-generated batch identifier:

- is rejected before a custom lifecycle recorder or PostgreSQL receives it;
- is represented by a null `batch_id` in bounded recovery evidence;
- is absent from the public `GatewayError`, structured response data, and
  exception cause; and
- cannot be recovered from the recorder because the recorder is not invoked.

Existing lifecycle tests prove the complementary recovery path: when a provider
identifier is valid but an independent recorder or PostgreSQL operation fails,
the validated identifier and observation order remain available and the original
persistence exception remains chained for authorized diagnosis.

The temporary write-capable implementation workflow is absent from this
verified implementation head. The final branch includes only production code,
deterministic tests, operator documentation, CHANGELOG entries, and immutable
RED/GREEN evidence.

## Final exact-head rule

This evidence file changes the pull-request head and therefore does not itself
constitute final-head verification. CI, security, automated review, independent
approval, branch protection, and repository policy must all succeed again on
the resulting exact final head and base before merge.
