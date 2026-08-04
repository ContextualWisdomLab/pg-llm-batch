# Idempotent GET retry TDD red evidence

The focused command

`uv run pytest -q tests/test_idempotent_get_retries.py`

failed on pre-implementation head `1f8208ee69850a346ff7005073d7e7169626f3f3` for the expected missing retry interface: `BatchAPIClient` did not accept `max_retry_attempts` and the module did not define `_parse_retry_after`.
