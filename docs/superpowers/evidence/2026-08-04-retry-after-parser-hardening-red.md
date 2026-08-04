# Retry-After Parser Hardening Red Evidence

- Pre-fix head: `0a2e82ad5e6d7ca34b99393dcc7a1ddaca7d44a9`
- Command: `uv run pytest -q tests/test_retry_after_parser_hardening.py`
- Expected result: failure before implementation
- Observed boundary failures: oversized ASCII decimal conversion and/or
  acceptance of non-ASCII decimal digits

The workflow rejected unrelated setup failures and proceeded only after the
focused regression suite failed for a parser assertion or conversion error.
