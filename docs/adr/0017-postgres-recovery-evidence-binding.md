# ADR 0017: Bind recovery receipts from exact inspected evidence

- **Status:** Proposed
- **Date:** 2026-08-16
- **Decision owners:** ContextualWisdomLab maintainers

## Context

Protected main already has three recovery-evidence primitives:

- content-free `PostgresRecoveryReceipt` metadata;
- descriptor-pinned backup-artifact SHA-256/size evidence; and
- packaged `schema.sql` SHA-256/size evidence.

A buyer still has to copy those fields by hand. Hand assembly lets a caller
attach a schema digest from one package build to a backup hashed from another
file, or attach a size that does not match the hashed bytes. That is a
composition gap, not a missing hash algorithm.

NIST SP 800-34 Rev. 1 treats backup integrity and recovery identity as
contingency-planning evidence. NIST SP 800-53 Rev. 5 CP-9/CP-10 require
information-system backups to be protected and recoverable. FIPS 180-4 defines
the SHA-256 digest the existing inspectors already emit. PostgreSQL 18 backup
documentation separates logical, physical, and continuous-archive/PITR methods;
the receipt already names those methods and must not invent a fourth.

Canonical product/TRD status remains owned by PR #192. Executable restore
remains owned by the #212 successor to #209. This decision must not rewrite
those surfaces or claim a dump/restore drill is complete.

## Decision

Add one keyword-only binder, `bind_postgres_recovery_receipt`, that:

1. accepts only exact `PostgresSchemaEvidence` and
   `PostgresBackupArtifactEvidence` instances;
2. copies schema and backup digests plus backup size from those objects;
3. rejects subclasses and namespace substitutes before attribute access;
4. rejects malformed evidence internals with a fixed inputs error;
5. constructs `PostgresRecoveryReceipt` and normalizes receipt-schema failures
   to a fixed metadata error without retaining receipt exception context; and
6. never accepts a parallel digest, path, DSN, credential, tenant scope, or
   backup-byte argument.

Logical backup execution and custom-format restore remain separate seams.

## Consequences

Operators can prove that a receipt's artifact identity equals the inspected
file and packaged schema before they restore. They still must run a reviewed
isolated restore drill before treating recovery as complete. Documentation
index updates stay on #192. Restore-seek documentation stays on #212.

## References

National Institute of Standards and Technology. (2015). *Secure hash standard
(SHS)* (FIPS PUB 180-4). https://doi.org/10.6028/NIST.FIPS.180-4

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation:
Chapter 25. Backup and restore*. https://www.postgresql.org/docs/18/backup.html

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST Special
Publication 800-34 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-34r1

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53 Rev. 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5
