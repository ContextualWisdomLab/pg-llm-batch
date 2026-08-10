# Structured error evidence integrity

## Purpose

`PgLlmBatchError.details` and `GatewayError.response_data` are structured diagnostic evidence. Before this repair, a caller that supplied a non-empty mapping could mutate that same mapping after exception construction and silently change the exception's later-observed evidence. The defect was aliasing at the constructor boundary, not provider parsing, persistence, transport, or logging.

The implemented contract is a **constructor-time snapshot** of the outer caller-owned mapping. This prevents later additions, removals, or replacements in the caller's mapping from rewriting the exception record observed by another consumer.

## Assurance boundary

The snapshot is intentionally a **shallow snapshot**:

- `PgLlmBatchError` copies the supplied outer `details` mapping when the exception is constructed.
- `GatewayError` copies the supplied outer `response_data` mapping once and exposes that same package-owned snapshot through both `response_data` and `details["response_data"]`.
- Existing messages, error codes, status codes, mapping types, and public attribute names remain unchanged.

This contract is **not immutable** evidence. A consumer that directly mutates `error.details` or `error.response_data` can still mutate the package-owned mapping, and nested mutable objects remain shared because the boundary is shallow. The repair therefore prevents post-construction drift through the original caller-owned mapping without claiming cryptographic integrity, append-only audit storage, or deep object immutability.

A deep copy was deliberately rejected as the default remedy. Arbitrary nested values may implement custom copying behavior, may not be copyable, and may make copy cost depend on caller-controlled object graphs. Deep copying would therefore widen the execution and compatibility boundary beyond the defect. Callers that need durable audit evidence must serialize and persist a separately governed bounded representation rather than treating a live Python exception object as an audit log.

## Test-first evidence

`tests/test_exceptions.py::test_error_detail_mappings_snapshot_constructor_inputs` mutates the original non-empty base-error details mapping and gateway response mapping after exception construction. The accepted behavior is that the exception keeps the constructor-time outer values and that `GatewayError.response_data` is the same package-owned snapshot referenced by `details["response_data"]`.

`tests/test_exception_evidence_documentation.py` keeps this doctoring boundary machine-checkable, including the distinction between a caller-independent constructor snapshot and stronger immutability claims.

## Security and assurance alignment

This repair is an engineering control aligned with evidence-integrity and secure-development principles; it is not a certification claim.

- **ISO/IEC 27002:2022** is the current ISO/IEC information-security-controls standard. Its control-oriented risk-management model supports treating integrity of security-relevant operational information as an explicit design concern rather than an accidental property.
- **NIST SP 800-53 Rev. 5, Release 5.2.0** is the current NIST control catalog release as of this doctoring update. The Audit and Accountability family, including AU-9 protection-of-audit-information principles, provides a useful assurance analogue: security-relevant evidence should not be modifiable through an unrelated authority path. A live exception is not itself an audit record, so this project uses the principle narrowly rather than claiming AU-9 compliance.
- **NIST SP 800-218** SSDF Version 1.1 remains the current final SSDF publication; a Version 1.2 revision is still draft as of 2026-08-10. This repair follows the SSDF practice of identifying a concrete software weakness, adding a focused regression, applying the smallest bounded correction, and preserving reviewable evidence.

## Rollback and compatibility

Rollback is a revert of the production snapshot commit plus its focused regression. No database migration, provider protocol, credential format, serialized schema, or release artifact format changes. If an embedding application intentionally relied on mutating the original mapping after exception construction to rewrite the exception, that behavior is now rejected as unsafe aliasing; direct mutation of the exception's own public mapping remains unchanged for compatibility.

## References (APA 7)

International Organization for Standardization, & International Electrotechnical Commission. (2022). *Information security, cybersecurity and privacy protection—Information security controls* (ISO/IEC Standard No. 27002:2022). https://www.iso.org/standard/75652.html

National Institute of Standards and Technology. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53 Rev. 5; Release 5.2.0). U.S. Department of Commerce. https://doi.org/10.6028/NIST.SP.800-53r5

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
