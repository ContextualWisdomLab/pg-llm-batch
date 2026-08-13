# ADR 0006: Resumable provider-result checkpoints

- **Status:** Accepted
- **Date:** 2026-08-06
- **Decision owners:** ContextualWisdomLab maintainers

## Context

Bounded result streaming prevents whole-file materialization, but a restarted consumer can replay records that were already durably applied. A record number alone cannot prove that the provider prefix is unchanged: content, blank-line framing, newline termination, or file identity may have changed.

## Decision

`StreamingBatchAPIClient` exposes immutable `BatchResultCheckpoint` evidence and a checkpointed iterator. Each checkpoint binds the validated batch identifier, pre-normalized endpoint alias, ordered provider file kind and identifier, file-local and batch-wide positions, and a SHA-256 digest over a domain-separated length-prefixed representation of every physical line through the acknowledged record.

Resume rescans from byte zero under the normal byte, line, record, timeout, retry-handoff, identifier, parser, and response-lifecycle limits. No later record is delivered until the supplied checkpoint is reproduced exactly. Changed acknowledged input or truncation at or before the checkpoint fails closed.

This is deliberately prefix-only evidence. Mutation or truncation **strictly after the acknowledged checkpoint** is outside the assurance boundary. A host that requires suffix or whole-stream immutability needs a stable provider validator, authenticated digest, or a separate **full-stream manifest** pass.

## Security boundary

SHA-256 provides deterministic change detection, not provider authentication or tenant authorization. The embedding host owns authentication, tenant/endpoint authorization, checkpoint-store integrity, rollback protection, and the transaction that couples a record's application effects to checkpoint advancement. Exactly-once delivery is not claimed by the package alone.

## Consequences

The design is provider-portable because it does not require HTTP Range support, but resume cost is linear in the acknowledged prefix. Existing aggregate and non-checkpointed streaming APIs remain available.

## Verification

Tests cover chunk independence, result-before-error order, exact resume suppression, changed prefix and file identity, truncation, newline/blank-line framing, local validation before external effects, deterministic early close, Python 3.10/3.12/3.14, and exact owned production coverage/docstrings.

## References

National Institute of Standards and Technology. (2015). *Secure Hash Standard (SHS)* (FIPS PUB 180-4). https://doi.org/10.6028/NIST.FIPS.180-4

Python Software Foundation. (2026). *hashlib — Secure hashes and message digests* (Python 3.14 documentation). https://docs.python.org/3.14/library/hashlib.html
