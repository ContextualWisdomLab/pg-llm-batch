# CLAUDE.md

## Tenant lifecycle invariants

- Preserve the standalone client, its four-argument recorder seam, and the explicit `standalone` database scope.
- Never derive tenant scope from provider metadata, remote identifiers, request bodies, endpoint aliases, or transport headers.
- Validate tenant scope before observation reservation, credential lookup, provider I/O, or database I/O.
- Bind validated scope as a parameter with transaction-local `set_config` before lifecycle table access.
- Include tenant scope in every lifecycle lookup, unique identity, conflict target, and operational status index.
- Keep row-level security enabled and forced. Production application roles are `NOSUPERUSER NOBYPASSRLS`.
- Keep owner-enforcement relaxation, legacy backfill, constraint migration, and forced-RLS restoration inside one atomic PostgreSQL statement.
- Keep `pg_llm_batch/schema.sql` and `docker/postgres/init/02_schema.sql` byte-for-byte identical.
- Maintain 100% production statement, branch, and public-docstring coverage. Add realistic migration, rollback, compatibility, security, and tenant-isolation tests before implementation changes.
