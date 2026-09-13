# OpenTelemetry packaging extra

## Operator action

Install the package-owned instrumentation API with the reviewed optional extra:

```bash
pip install 'pg-llm-batch[observability]'
```

This extra installs `opentelemetry-api>=1.44,<2` and does **not** install
`opentelemetry-sdk`. The base package remains OpenTelemetry-independent.
Applications that want exported telemetry must separately select, configure,
and operate a compatible SDK, resource attributes, processors or readers,
exporters, collector endpoints, sampling, credentials, and retention.

This separation follows the OpenTelemetry library-instrumentation boundary:
libraries depend on the API, while the embedding application owns the SDK and
emission pipeline. It also uses the Python packaging `optional-dependencies`
contract, which maps an extra to conditional `Requires-Dist` metadata rather
than silently widening every installation.

## Supply-chain and compatibility boundary

The `observability` extra is represented in `pyproject.toml`, the built
wheel/sdist metadata, and the repository `uv.lock`. The lock is generated and
verified with repository-pinned uv 0.12.3; it must not be hand edited. Clean
installation tests prove both directions:

- base wheel: `opentelemetry` is absent;
- `pg-llm-batch[observability]`: the OpenTelemetry API is present and
  `pg_llm_batch.observability.OpenTelemetryBatchAPIClient` is importable.

`opentelemetry-sdk` remains a host deployment decision. Installing the package
extra alone is not evidence that telemetry is exported, retained, secured, or
compliant with any certification regime.

## Rollback

A host can remove package-level OpenTelemetry support by reinstalling the base
package without the extra. The host must separately remove or reconfigure any
SDK/exporter components it owns. Package rollback does not delete host telemetry
or change backend retention.

## References

OpenTelemetry Authors. (n.d.). *Instrumentation*. OpenTelemetry. Retrieved
August 14, 2026, from
https://opentelemetry.io/docs/languages/python/instrumentation/

Python Packaging Authority. (n.d.). *pyproject.toml specification*. Python
Packaging User Guide. Retrieved August 14, 2026, from
https://packaging.python.org/en/latest/specifications/pyproject-toml/

Python Packaging Authority. (n.d.). *Core metadata specifications*. Python
Packaging User Guide. Retrieved August 14, 2026, from
https://packaging.python.org/en/latest/specifications/core-metadata/
