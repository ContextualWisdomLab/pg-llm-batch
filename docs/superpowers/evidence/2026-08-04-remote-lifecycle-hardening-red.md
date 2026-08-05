# Durable Remote Lifecycle Hardening Red Evidence

Pre-hardening head: `3c58a20d2c0159637853aeaeb7c4984110dec9d5`

Focused tests were added without changing the lifecycle implementation. They returned a non-zero pytest status for the intended reasons:

- no PostgreSQL-owned observation sequence or persisted observation order existed;
- the durable client had no pre-request reservation seam;
- reservation failure could not block provider I/O with structured evidence;
- persistence did not accept an observation order;
- provider metadata serialization was neither finite-JSON-safe nor byte-bounded.

The one-shot workflow required failure signatures for schema ordering, client reservation, and persistence ordering before recording this evidence.
