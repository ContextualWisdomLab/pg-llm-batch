# ADR: Standalone operation and embedding-host composition boundary

## Status and maturity

**IMPLEMENTED-ON-PROTECTED-MAIN.** This ADR records the dual standalone/library product boundary already represented by the protected-main CLI, Docker/Compose artifacts, public Python package, credential-provider seam, and optional observability composition. It does not make any sibling ContextualWisdomLab service a runtime prerequisite.

## Context and decision drivers

`pg-llm-batch` is useful in two operational shapes: a standalone PostgreSQL-backed component operated through its CLI/container profile, and an embedded library inside an application that already owns authentication, ingress, secrets, tenancy, telemetry, and business transactions. Commercial reuse requires the batch engine to remain independently deployable without creating hidden dependencies on a particular gateway, service mesh, user directory, or CWL product.

At the same time, an embedding host must be able to supply credentials and platform policy without forking provider/batch logic or sharing an application database through undocumented coupling.

## Alternatives considered

1. **Mandatory network service architecture.** Rejected because every consumer would need to deploy an extra service even when in-process Python composition is sufficient.
2. **Library-only architecture with no standalone operator surface.** Rejected because it would shift schema initialization, configuration, health, and provider lifecycle composition into every buyer integration.
3. **Direct cross-service database coupling to CWL siblings.** Rejected because it destroys bounded-context ownership and independent deployment.
4. **One package with standalone and embedded composition surfaces.** Chosen.

## Decision

The package remains independently usable in a **standalone** deployment and directly importable by an **embedding host**.

Protected main provides a CLI, package schema/bootstrap helpers, component/PostgreSQL container assets, Compose example, health surface, and provider operation commands. The Python API exposes `BatchAPIClient`, `DurableBatchAPIClient`, `PostgresBatchOrchestrator`, token/configuration components, and a callable credential-provider seam.

Embedding hosts may supply their own credential resolver and own authentication, user/workload identity, tenant mapping, ingress/WAF/service-mesh policy, global OpenTelemetry SDK/exporters, database backup/restore, retention, and cross-system business transactions. Sibling CWL services may integrate through explicit APIs/artifacts, but pg-llm-batch does not require naruon, contextual-orchestrator, or another sibling repository to function.

## Consequences and non-goals

- Standalone operators receive a coherent product surface without writing an application host.
- Embedded users can reuse batch/provider logic without adopting package-owned global platform policy.
- Some responsibilities deliberately remain deployment-owned, so the package cannot claim host authentication, universal tenant authorization, global observability retention, or infrastructure ingress controls.
- The package does not become a universal secret manager or workflow engine.
- No cross-service application-database access is authorized by this composition model.

## Failure and recovery

Package validation/configuration failures surface at the local API/CLI boundary and must not be hidden as successful platform composition. Provider/database failures retain the package-specific recovery semantics documented by their owning decisions.

The embedding host remains responsible for recovering its own ingress, identity, external secret manager, global telemetry backend, business transaction, and deployment infrastructure. A sibling-service outage must degrade only integrations that actually depend on that sibling, not base standalone operation.

## Security, privacy, and governance impact

The standalone/default path may use PostgreSQL-backed `com_config`/`com_secrets` and documented bootstrap environment variables. Host integrations may replace provider credential resolution through the public `Callable[[str], GatewayCredentials]` seam. Provider credentials must remain scoped to provider requests and must not become general host identity.

Authentication, trusted tenant selection, purpose-bound PII authorization, database service identity, ingress policy, backup access, and external secret lifecycle remain host/deployment governance duties unless a future ADR explicitly transfers one of those authorities.

## Compatibility and migration

The public Python imports, CLI commands/options, schema, and supported deployment artifacts are compatibility surfaces governed by `docs/product/API_CONTRACT.md`. A new mandatory network hop, sibling service, database, or global telemetry runtime would be a material breaking architecture change.

ACTIVE-PR #85, #87, #89, #70, and #91 harden CLI secret input, resource ownership, bootstrap precedence, health serving, and Compose network exposure. They remain overlays until integrated and must not be described as protected-main behavior prematurely.

## Verification and acceptance

Acceptance requires package import/public-surface tests, CLI parser/behavior tests, configuration/credential-provider tests, Compose/container validation, readiness tests, package-build tests, and supported-version CI. Documentation checks must continue to distinguish host-owned authority from package-owned behavior and shipped behavior from ACTIVE-PR hardening.

## Rollback and supersession

A composition regression may revert to the last protected standalone/library surface if doing so does not reintroduce a known security defect. This ADR can be superseded only by a decision that explicitly states which standalone or host-owned responsibilities move, provides compatibility/migration guidance for existing embedders/operators, and preserves an independently deployable product or deliberately changes that requirement with buyer-impact evidence.