# Standalone Compose loopback publishing

## Decision

The bundled `docker-compose.yml` is a standalone/developer profile. Its published PostgreSQL (`5432`) and component health (`8080`) ports bind to IPv4 loopback (`127.0.0.1`) by default.

Remote access is not silently inherited from this profile. A production deployment that needs external ingress must define an explicit deployment-specific network and authorization boundary rather than broadening the bundled standalone mappings.

## Security rationale

Docker's Compose service reference defines the short port syntax as `[HOST:]CONTAINER[/PROTOCOL]` and warns that omitting the host IP binds the published port to all host interfaces (`0.0.0.0`). Docker's port-publishing documentation likewise states that a mapping that includes `127.0.0.1` is accessible only from the Docker host. The previous `"5432:5432"` and `"8080:8080"` mappings therefore created a broader default host-network surface than the standalone workflow requires.

The loopback binding preserves the documented local commands:

- host-side PostgreSQL access through `localhost:5432`;
- host-side readiness checks through `localhost:8080`;
- Compose-internal service-to-service traffic over the project network.

It intentionally does not claim that loopback binding replaces authentication, tenant isolation, firewalling, ingress policy, or production deployment hardening.

## Verification contract

`tests/test_compose_network_boundary.py` requires the exact loopback mappings and rejects the prior all-interface short mappings. CI also renders the Compose model with `docker compose config` and builds both component and PostgreSQL images.

Release evidence must be taken from the exact source head under review. Organization-provided security/SAST workflows may independently exercise a synthetic merge ref; those results are integration evidence and are not relabeled as exact-source proof.

## References

Docker, Inc. (n.d.). *Define services in Docker Compose*. Docker Documentation. Retrieved August 9, 2026, from https://docs.docker.com/reference/compose-file/services/

Docker, Inc. (n.d.). *Port publishing and mapping*. Docker Documentation. Retrieved August 9, 2026, from https://docs.docker.com/engine/network/port-publishing/
