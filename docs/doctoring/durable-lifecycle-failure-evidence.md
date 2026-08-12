# Durable lifecycle failure evidence

## Scope

`DurableBatchAPIClient` and `TenantDurableBatchAPIClient` expose bounded recovery evidence when observation-order reservation fails before provider I/O or lifecycle persistence fails after a provider effect. This record documents only that exported exception boundary; it does not claim that database logs, host logs, caller-owned serializers, or arbitrary injected implementations are confidential by themselves.

## Decision

The public `response_data["error_type"]` field is retained for compatibility, but arbitrary Python class names are no longer copied into it. Package code maps caught ordinary `Exception` instances into the finite vocabulary `ValidationError`, `ValueError`, `OSError`, or `RuntimeError`. Unknown implementation exceptions collapse to `RuntimeError`.

Trusted reconciliation fields remain unchanged: operation, phase, validated endpoint alias, validated batch identifier when available, reserved observation order when available, and the host-authorized tenant scope for tenant-qualified clients. Reservation and persistence remain distinguishable through the `phase` field.

The original exception object is not re-raised as `GatewayError.__cause__`, and the exported `GatewayError` is raised only after leaving the handler for the lower-layer exception. This is deliberate: Python 3.14 documents that `raise new_exception from None` suppresses the prior exception for normal traceback display but still leaves that exception available through `__context__` for introspection. Raising the package-owned error after the handler has ended avoids retaining the lower-layer object in either `__cause__` or `__context__`.

The implementation catches `Exception`, not `BaseException`, preserving process/control-flow exceptions outside this recovery conversion boundary unless a separately reviewed contract explicitly changes that behavior.

## Security and reliability rationale

Dynamic exception names and chained lower-layer exceptions are uncontrolled diagnostic inputs. They can create high-cardinality evidence and may retain credentials, DSNs, rejected values, provider content, or other implementation state. CWE-209 identifies generation of error messages containing sensitive information as a software weakness. A finite package-owned category plus trusted recovery fields provides operator reconciliation value without making lower-layer exception objects part of the exported package contract.

## Verification

The regression suite injects custom exceptions whose type names and messages contain unique secret-like sentinels and exercises both standalone and tenant-qualified reservation and persistence paths. It requires:

- no sentinel in `str(error)`, `repr(error)`, or `response_data`;
- `__cause__ is None` and `__context__ is None`;
- the finite error-type vocabulary;
- preservation of phase, endpoint alias, batch identifier, observation order, and trusted tenant scope; and
- unchanged successful lifecycle behavior through the existing suite.

The existing Python 3.10, 3.12, and 3.14 CI matrix, exact owned-production coverage gate, docstring gate, SAST, and security workflows remain authoritative for the final exact head.

## References

MITRE. (2026). *CWE-209: Generation of error message containing sensitive information (Version 4.20)*. Common Weakness Enumeration. https://cwe.mitre.org/data/definitions/209.html

Python Software Foundation. (2026). *Built-in exceptions — Python 3.14.6 documentation*. https://docs.python.org/3.14/library/exceptions.html
