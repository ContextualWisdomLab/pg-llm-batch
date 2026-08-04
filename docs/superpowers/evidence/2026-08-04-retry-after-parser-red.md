# Retry-After Parser Red Evidence

Pre-implementation head: `4dc5041bcf508c8f5fe4477c8ddd12710b6fd423`

The focused hostile-header tests were added without changing production code and returned a non-zero pytest status for the intended reasons:

- non-ASCII decimal characters were accepted by `str.isdecimal()`;
- a 10,000-digit ASCII delay leaked Python's decimal-to-integer `ValueError`;
- a fullwidth digit selected an exact two-second wait instead of bounded fallback.

The one-shot workflow required all three failure signatures before recording this evidence.
