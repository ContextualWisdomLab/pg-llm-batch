"""JSONB adaptation shared by pg8000 admission and production runtime.

pg8000 1.31.5 sends JSON as serialized text and returns JSON values
deserialized. ``Pg8000DriverAdapter`` reuses this serializer after exact-artifact
admission so JSONB semantics stay in one reviewed anti-corruption boundary rather
than being copied into a second production implementation. The historical
``candidate`` names preserve the migration evidence lineage; protected
integration and immutable release remain separate authorities.
"""

from __future__ import annotations

import json


class Pg8000CandidateJsonbError(RuntimeError):
    """Report an invalid pg8000 JSONB value without reflecting payload content.

    The error intentionally contains no serialized value because batch payloads
    may contain purpose-bound user or provider content. Callers can classify the
    adaptation failure without turning diagnostics into a content leak.
    """


def adapt_pg8000_jsonb(value: object) -> str:
    """Serialize one validated value for pg8000 DB-API JSONB parameter binding.

    PostgreSQL JSON/JSONB does not admit IEEE non-finite numeric literals, and an
    isolated Unicode surrogate cannot be encoded as the UTF-8 client text sent to
    PostgreSQL. The adapter therefore fails closed before database I/O for either
    case and for objects that Python's JSON encoder cannot represent. Non-ASCII
    text is retained as Unicode rather than escaped so production and admission
    paths exercise the same client-encoding boundary used by real multilingual
    batch payloads.

    Args:
        value: A caller-validated JSON-compatible Python value.

    Returns:
        Compact UTF-8-encodable JSON text suitable for a pg8000 DB-API parameter.

    Raises:
        Pg8000CandidateJsonbError: If the value is not finite JSON or cannot be
            represented as UTF-8 JSON text.
    """
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        serialized.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise Pg8000CandidateJsonbError(
            "PostgreSQL driver JSONB value is invalid"
        ) from None
    return serialized
