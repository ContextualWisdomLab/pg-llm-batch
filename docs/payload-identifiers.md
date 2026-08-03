# Payload identifier entropy

Prepared JSONL payloads use identifiers in the form:

```text
file_<32 lowercase hexadecimal characters>
```

The suffix preserves the complete 128-bit UUID value. Earlier builds retained
only 12 hexadecimal characters (48 bits), which made collision risk material at
large fleet and long-retention scales despite the database uniqueness constraint.
A collision would otherwise convert a new preparation into an update of an
existing `llm_batch_file_payloads` row.

The full identifier remains compatible with the provider resource identifier
policy, is safe as a `memory://` reference, and is stored under the existing
unique `file_id` constraint.
