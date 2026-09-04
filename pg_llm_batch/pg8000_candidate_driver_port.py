"""Candidate-only pg8000 implementation of the PostgreSQL driver port.

The commercial migration needs a connection factory, not only cursor wrappers.
pg8000 1.31.5 accepts explicit DB-API connection keyword arguments but does not
provide libpq conninfo or service-file parsing. This adapter therefore owns a
bounded anti-corruption parser for the single-host PostgreSQL URI and keyword
conninfo forms already needed by pg-llm-batch. Service selectors, query options,
multi-host/socket forms, and other libpq-only semantics remain fail closed until
they have separate compatibility evidence.

The module does not import pg8000. An exact candidate DB-API module must be
injected after artifact, license, integrity, and environment admission, keeping
pg8000 out of the committed production dependency graph while issue #322 remains
open.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import ModuleType
from typing import cast
from urllib.parse import quote, unquote, urlsplit

from .pg8000_driver_candidate_adapter import (
    Pg8000CandidateAdapterError,
    validate_pg8000_dbapi_module,
)
from .pg8000_driver_candidate_errors import (
    is_pg8000_candidate_undefined_function,
)
from .pg8000_driver_candidate_jsonb import adapt_pg8000_jsonb
from .pg8000_thread_affine_candidate_adapter import (
    Pg8000ThreadAffineCandidateConnectionAdapter,
)
from .postgres_driver_port import PostgresConnectionPort, PostgresDriverPort


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_ALLOWED_PARAMETER_KEYS = frozenset({"user", "password", "host", "port", "dbname"})
_DEFAULT_PORT = 5432
_MIN_PORT = 1
_MAX_PORT = 65_535
_AMBIGUOUS_HOST_TOKENS = frozenset("/?,#@[]\\%")
_KEYWORD_SEPARATOR = " "


class Pg8000CandidateInvalidConninfoError(Pg8000CandidateAdapterError):
    """Identify only failures at the candidate connection-selector boundary.

    The error message never reflects the supplied selector or credentials. A
    failure means the candidate cannot represent that PostgreSQL selector under
    the currently proved URI/keyword contract; it does not mean the database
    rejected a connection attempt.
    """


def _invalid_selector(*, unsupported: bool = False) -> Pg8000CandidateInvalidConninfoError:
    """Create one non-content-bearing selector error for malformed or missing data."""
    if unsupported:
        return Pg8000CandidateInvalidConninfoError(
            "PostgreSQL connection selector is unsupported"
        )
    return Pg8000CandidateInvalidConninfoError(
        "PostgreSQL connection selector is invalid"
    )


def _contains_control(value: str) -> bool:
    """Return whether text contains ASCII control or DEL framing characters."""
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)


def _validate_percent_encoding(value: str) -> None:
    """Reject incomplete or non-hex percent escapes before URI decoding."""
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            raise _invalid_selector()
        index += 3


def _decode_component(value: str, *, allow_empty: bool = False) -> str:
    """Decode one UTF-8 URI component after strict percent and framing checks."""
    _validate_percent_encoding(value)
    try:
        decoded = unquote(value, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, UnicodeError):
        raise _invalid_selector() from None
    if (not decoded and not allow_empty) or _contains_control(decoded) or "\x00" in decoded:
        raise _invalid_selector()
    return decoded


def _parse_port(value: object) -> int:
    """Return one exact TCP port while rejecting bools and out-of-range values."""
    if type(value) is int:
        port = value
    elif type(value) is str and value.isascii() and value.isdigit():
        port = int(value)
    else:
        raise _invalid_selector()
    if port < _MIN_PORT or port > _MAX_PORT:
        raise _invalid_selector()
    return port


def _validate_host(host: str) -> str:
    """Keep one TCP host while rejecting forms that imply unsupported selectors.

    Commas would turn PostgreSQL URI authority into a multi-host selector;
    percent escapes can encode Unix-socket paths or IPv6 zone identifiers; and
    whitespace/backslashes or URI delimiters make rendering ambiguous. Those
    contracts require separate compatibility evidence and therefore fail closed
    instead of being passed to pg8000 as a misleading single hostname.
    """
    if (
        not host
        or _contains_control(host)
        or any(character.isspace() for character in host)
        or any(token in host for token in _AMBIGUOUS_HOST_TOKENS)
    ):
        raise _invalid_selector()
    return host


def _parse_postgresql_uri(dsn: str) -> dict[str, str]:
    """Parse the candidate's reviewed single-host PostgreSQL URI subset.

    Service selectors, query parameters, fragments, multi-host forms, Unix-socket
    selectors, and libpq-specific options remain outside this bounded slice. They
    fail closed rather than being approximated by pg8000 connection arguments.
    """
    if type(dsn) is not str or not dsn or _contains_control(dsn):
        raise _invalid_selector()
    if not (dsn.startswith("postgresql://") or dsn.startswith("postgres://")):
        raise _invalid_selector(unsupported=True)

    try:
        parsed = urlsplit(dsn)
    except ValueError:
        raise _invalid_selector() from None

    if parsed.scheme not in {"postgresql", "postgres"}:
        raise _invalid_selector(unsupported=True)
    if parsed.query or parsed.fragment:
        raise _invalid_selector(unsupported=True)
    if not parsed.netloc or parsed.username is None or parsed.hostname is None:
        raise _invalid_selector()
    if not parsed.path.startswith("/") or len(parsed.path) <= 1:
        raise _invalid_selector()
    raw_database = parsed.path[1:]
    if "/" in raw_database:
        raise _invalid_selector(unsupported=True)

    user = _decode_component(parsed.username)
    password = (
        _decode_component(parsed.password, allow_empty=True)
        if parsed.password is not None
        else None
    )
    host = _validate_host(parsed.hostname)
    database = _decode_component(raw_database)
    try:
        port = parsed.port if parsed.port is not None else _DEFAULT_PORT
    except ValueError:
        raise _invalid_selector() from None
    port = _parse_port(port)

    result = {
        "user": user,
        "host": host,
        "port": str(port),
        "dbname": database,
    }
    if password is not None:
        result["password"] = password
    return result


def _read_keyword_value(dsn: str, start: int) -> tuple[str, int]:
    """Read one bounded libpq-style keyword value and return the next offset.

    The candidate deliberately accepts only ASCII-space separators. Single-quoted
    values and backslash escaping follow the portable conninfo forms needed by
    current deployments, while tabs/newlines and unterminated escapes fail closed
    instead of acquiring implicit libpq parser semantics.
    """
    if start >= len(dsn):
        return "", start

    quoted = dsn[start] == "'"
    index = start + 1 if quoted else start
    characters: list[str] = []
    while index < len(dsn):
        character = dsn[index]
        if quoted and character == "'":
            index += 1
            if index < len(dsn) and dsn[index] != _KEYWORD_SEPARATOR:
                raise _invalid_selector()
            return "".join(characters), index
        if not quoted and character == _KEYWORD_SEPARATOR:
            return "".join(characters), index
        if character == "\\":
            index += 1
            if index >= len(dsn):
                raise _invalid_selector()
            escaped = dsn[index]
            if _contains_control(escaped):
                raise _invalid_selector()
            characters.append(escaped)
            index += 1
            continue
        if character == "'" and not quoted:
            raise _invalid_selector()
        if _contains_control(character) or character == "\x00":
            raise _invalid_selector()
        characters.append(character)
        index += 1

    if quoted:
        raise _invalid_selector()
    return "".join(characters), index


def _parse_keyword_conninfo(dsn: str) -> dict[str, str]:
    """Parse the reviewed single-host subset of PostgreSQL keyword conninfo.

    Only ``user``, ``password``, ``host``, ``port``, and ``dbname`` are admitted.
    Duplicate keys are rejected rather than relying on libpq's last-value-wins
    behavior because duplicated authority is ambiguous at the migration boundary.
    Service-file selectors and transport options remain explicit unsupported gaps.
    """
    if type(dsn) is not str or not dsn or _contains_control(dsn):
        raise _invalid_selector()
    if any(character.isspace() and character != _KEYWORD_SEPARATOR for character in dsn):
        raise _invalid_selector()

    index = 0
    params: dict[str, str] = {}
    while index < len(dsn):
        while index < len(dsn) and dsn[index] == _KEYWORD_SEPARATOR:
            index += 1
        if index >= len(dsn):
            break

        key_start = index
        while index < len(dsn) and dsn[index] not in {_KEYWORD_SEPARATOR, "="}:
            index += 1
        key = dsn[key_start:index]
        if not key:
            raise _invalid_selector()
        while index < len(dsn) and dsn[index] == _KEYWORD_SEPARATOR:
            index += 1
        if index >= len(dsn) or dsn[index] != "=":
            raise _invalid_selector()
        index += 1
        while index < len(dsn) and dsn[index] == _KEYWORD_SEPARATOR:
            index += 1

        if key not in _ALLOWED_PARAMETER_KEYS:
            raise _invalid_selector(unsupported=True)
        if key in params:
            raise _invalid_selector()

        value, index = _read_keyword_value(dsn, index)
        params[key] = value

    return _validate_parameter_mapping(params)


def _validate_parameter_mapping(params: Mapping[str, str]) -> dict[str, str]:
    """Copy exact built-in string values from the candidate parameter set."""
    if not isinstance(params, Mapping):
        raise _invalid_selector()
    copied: dict[str, str] = {}
    for key, value in params.items():
        if type(key) is not str or key not in _ALLOWED_PARAMETER_KEYS:
            raise _invalid_selector(unsupported=True)
        if type(value) is not str or _contains_control(value) or "\x00" in value:
            raise _invalid_selector()
        copied[key] = value
    if "user" not in copied or "host" not in copied or "dbname" not in copied:
        raise _invalid_selector()
    if not copied["user"] or not copied["dbname"]:
        raise _invalid_selector()
    copied["host"] = _validate_host(copied["host"])
    copied["port"] = str(_parse_port(copied.get("port", str(_DEFAULT_PORT))))
    return copied


def _render_host(host: str) -> str:
    """Render a validated single host, adding URI brackets only for IPv6 form."""
    if ":" in host:
        return f"[{host}]"
    return host


class Pg8000CandidateDriverAdapter(PostgresDriverPort):
    """Prove the pg8000 driver port on bounded single-host PostgreSQL selectors.

    The injected module must already be the exact candidate artifact. This class
    supplies no artifact discovery, dependency installation, or fallback. It
    converts only reviewed URI/keyword fields to pg8000 DB-API keyword arguments
    and wraps the resulting connection in the existing thread-affine candidate
    ACL.
    """

    def __init__(self, dbapi_module: ModuleType) -> None:
        validate_pg8000_dbapi_module(dbapi_module)
        connect = vars(dbapi_module).get("connect")
        if not callable(connect):
            raise Pg8000CandidateAdapterError(
                "PostgreSQL driver connection factory is incompatible"
            )
        self._dbapi_module = dbapi_module
        self._connect = connect

    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> PostgresConnectionPort:
        """Open one candidate connection from a proved selector and finite timeout.

        The original DSN is never forwarded to pg8000. Parsed values are supplied
        as explicit DB-API keywords so unsupported libpq selector semantics cannot
        be silently inherited or misrepresented.
        """
        if connect_timeout_seconds is not None and (
            type(connect_timeout_seconds) is not int or connect_timeout_seconds <= 0
        ):
            raise Pg8000CandidateInvalidConninfoError(
                "PostgreSQL driver timeout is invalid"
            )
        params = self.parse_conninfo(dsn)
        kwargs: dict[str, object] = {
            "user": params["user"],
            "host": params["host"],
            "port": _parse_port(params["port"]),
            "database": params["dbname"],
        }
        if "password" in params:
            kwargs["password"] = params["password"]
        if connect_timeout_seconds is not None:
            kwargs["timeout"] = connect_timeout_seconds
        raw_connection = self._connect(**kwargs)
        return Pg8000ThreadAffineCandidateConnectionAdapter(raw_connection)

    def parse_conninfo(self, dsn: str) -> Mapping[str, str]:
        """Parse only the currently proved URI or keyword selector subsets."""
        if type(dsn) is not str or not dsn:
            raise _invalid_selector()
        if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
            return _parse_postgresql_uri(dsn)
        return _parse_keyword_conninfo(dsn)

    def make_conninfo(self, params: Mapping[str, str]) -> str:
        """Render the proved parameter subset as a safely percent-encoded URI."""
        copied = _validate_parameter_mapping(params)
        user = quote(copied["user"], safe="")
        password = copied.get("password")
        credentials = user
        if password is not None:
            credentials += f":{quote(password, safe='')}"
        host = _render_host(copied["host"])
        database = quote(copied["dbname"], safe="")
        return f"postgresql://{credentials}@{host}:{copied['port']}/{database}"

    def jsonb(self, value: object) -> object:
        """Use the separately admitted candidate JSONB serialization boundary."""
        return adapt_pg8000_jsonb(value)

    def is_invalid_conninfo(self, error: BaseException) -> bool:
        """Recognize only errors emitted by this candidate selector boundary."""
        return isinstance(error, Pg8000CandidateInvalidConninfoError)

    def is_undefined_function(self, error: BaseException) -> bool:
        """Classify SQLSTATE 42883 through the exact injected DB-API authority."""
        return is_pg8000_candidate_undefined_function(
            error,
            dbapi_module=cast(object, self._dbapi_module),
        )
