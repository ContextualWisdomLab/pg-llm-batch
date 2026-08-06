# Doctoring: resumable result checkpoint assurance

## Assurance claim

The opt-in checkpointed streaming API gives an embedding host deterministic,
bounded evidence that the provider-result physical stream prefix through one
acknowledged record is unchanged when the host later resumes. The implementation
uses SHA-256, domain separation, and explicit length framing so logically
ambiguous concatenations and transport chunk boundaries do not define identity.

The supported claim is limited:

> Given the same validated batch identity, endpoint alias, ordered provider file
> identifiers, physical line bytes, and newline-termination states, the client
> reproduces the same checkpoint independently of HTTP chunking. Changed prefix
> input is rejected before any record after the supplied checkpoint is yielded.

The checkpoint does not attest bytes or records outside that reproduced prefix.
Mutation or truncation strictly after the acknowledged checkpoint is therefore
not detected. A host that requires whole-stream immutability needs a stable
provider validator or authenticated digest, or a separate full-stream manifest
that is established and compared under its own bounded lifecycle contract.

The implementation does not claim provider authenticity, non-repudiation,
protection from a host that can replace both stream and checkpoint, or automatic
exactly-once delivery to an external sink.

## Evidence-to-control mapping

| Risk | Control | Deterministic evidence |
| --- | --- | --- |
| Replay after worker restart | Resume suppresses records through the exact acknowledged checkpoint | Resume and final-checkpoint tests |
| Provider file replacement | File kind and validated file identifier are hash-framed | Changed-file-identity test |
| Mutation before resume point | Every preceding physical line is hash-framed | Prefix mutation tests |
| Truncation at or before checkpoint | End-of-stream without exact match fails closed | Missing-checkpoint test |
| Suffix mutation or truncation after checkpoint | Explicitly outside the prefix assurance claim | Authoritative boundary contract |
| Blank-line CPU/framing ambiguity | Blank lines consume the existing batch-wide physical-line budget and digest | Blank-line mutation and framing tests |
| CRLF/final-line ambiguity | Raw physical bytes and newline-termination state are distinct digest fields | Chunk/framing tests |
| Delimiter ambiguity | Every digest field has a typed tag and fixed-width length prefix | Deterministic checkpoint comparison tests |
| Credential or network side effects on invalid local evidence | Checkpoint type and request identity are validated first | Pre-network validation tests |
| Sensitive provider data in diagnostics | Mismatch diagnostics contain only finite classifications and positions | Body-free mismatch assertions |
| Resource exhaustion during resume | Existing total-byte, line-byte, physical-line, record, timeout, and retry-handoff limits remain active | Existing streaming limit suite plus checkpoint coverage |
| Leaked HTTP response after early exit | Context manager closes outer iterator, nested iterator, and response | Early-close checkpoint test |

## Digest construction

The digest is SHA-256 over a sequence of frames. Each frame is encoded as:

```text
2-byte big-endian tag length
+ tag bytes
+ 8-byte big-endian payload length
+ payload bytes
```

The sequence begins with a versioned domain, batch identifier, and endpoint
alias. Each ordered provider file adds file kind and file identifier frames. Each
physical line then adds file-local line number, exact bytes excluding the LF
separator, and one byte indicating whether LF terminated the line. The digest is
copied after a nonblank line is parsed as one JSON object. The copy operation
preserves incremental bounded hashing while allowing later records to extend the
same prefix state.

This framing is an internal versioned serialization contract. Consumers must
persist all checkpoint fields and must not reconstruct or compare only the
digest. A future incompatible framing change requires a new schema version and
explicit compatibility decision.

## Host integration requirements

1. Persist the entire immutable checkpoint only after the corresponding record's
   application effects are durable.
2. For exactly-once sink semantics, commit sink effects and checkpoint advancement
   in one host-owned transaction or use an equivalently proven idempotency key.
3. Protect checkpoint storage against unauthorized mutation and rollback. An
   HMAC, signature, append-only log, tenant-qualified database constraint, or
   transactional outbox may be appropriate at the host boundary.
4. Bind the checkpoint to the authenticated tenant and endpoint authorization
   context outside this package. The package validates equality but does not
   authenticate the alias or tenant.
5. Treat checkpoint mismatch as an operator-visible reconciliation event. Do not
   silently discard it, rewrite the stored checkpoint, or resume from a later
   record number.
6. Expect a full bounded prefix rescan. Size provider retention windows, rate
   limits, timeout policy, and worker capacity accordingly.
7. Do not treat successful prefix reproduction as evidence that the unseen suffix
   is complete or immutable. Add a provider validator, authenticated digest, or
   separate full-stream manifest when that stronger property is required.
8. Use `open_checkpointed_batch_records()` when processing may stop early so
   provider responses close deterministically.

## Failure handling

- `checkpoint_status=mismatch` means a record appeared at the expected logical
  position but the complete checkpoint differed. Possible causes include prefix
  content mutation, changed file identity, framing changes, inserted or removed
  records, or the wrong stored checkpoint.
- `checkpoint_status=not_found` means the bounded stream ended before the stored
  record count was reached. Treat this as truncation at or before the checkpoint,
  retention loss, or wrong checkpoint identity.
- Successful reproduction means only that the bounded acknowledged prefix
  matched. It does not classify changes strictly after that checkpoint.
- Validation errors occur before provider I/O for malformed checkpoint objects or
  request identity mismatch.

Diagnostics intentionally omit provider file identifiers, batch identifiers,
record bodies, URLs, and credentials. Operators should correlate using their own
protected job identity rather than weakening this public error boundary.

## Scientific and standards basis

FIPS 180-4 defines SHA-256 as a secure hash algorithm whose digest can be used to
detect whether a message has changed. The Python standard library exposes
incremental `hashlib.sha256()` update, copy, and hexadecimal digest operations,
which support bounded prefix hashing without retaining the full stream. The
security conclusion in this project is intentionally narrower than collision
resistance alone: digest framing, identity fields, bounded parsing, and trusted
checkpoint storage are all required for the resume claim.

## APA 7 references

National Institute of Standards and Technology. (2015). *Secure Hash Standard
(SHS)* (Federal Information Processing Standards Publication 180-4).
https://doi.org/10.6028/NIST.FIPS.180-4

Python Software Foundation. (2026). *hashlib—Secure hashes and message digests*
(Python 3.14 documentation). https://docs.python.org/3.14/library/hashlib.html
