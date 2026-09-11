"""Exercise the exact pg8000 candidate against a real PostgreSQL boundary.

This script is intentionally outside pytest discovery. CI installs one immutable
pg8000 candidate artifact and runs this smoke against the repository PostgreSQL
image without adding the candidate to the production dependency graph. The
checks cover the candidate URI, keyword, and explicit service connection
selectors, portable connection/cursor ACL, thread-affine connection use,
transaction, parameter, JSONB, UUID/timestamp, affected-row, narrow PostgreSQL
error classification, restore-catalog inspection, transport recovery,
transaction-local tenant semantics, and the production adapter's authenticated
remote-TLS boundary that must be proven before candidate promotion.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import metadata
from ipaddress import ip_address
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Iterator
import uuid

from pg8000 import dbapi

from pg_llm_batch.pg8000_candidate_driver_port import Pg8000CandidateDriverAdapter
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver
from pg_llm_batch.pg8000_driver_adapter import (
    Pg8000DriverAdapter,
    Pg8000DriverTlsPolicyError,
)
from pg_llm_batch.pg8000_driver_candidate_jsonb import adapt_pg8000_jsonb
from pg_llm_batch.postgres_restore_acceptance import inspect_postgres_restore_catalog

_EXPECTED_VERSION = "1.31.5"
_EXPECTED_DATABASE = "pgllm"
_EXPECTED_USER = "pgllm"
_CREDENTIAL_FREE_DSN = "postgresql://pgllm@127.0.0.1:5432/pgllm"
_TLS_DIRECTORY = "/tmp/pg-llm-batch-tls"


def _candidate_driver() -> Pg8000CandidateDriverAdapter:
    """Bind the exact admitted pg8000 DB-API module to the candidate driver port."""
    return Pg8000CandidateDriverAdapter(dbapi)


def _candidate_password() -> str:
    """Read the ephemeral CI credential without placing it in process arguments."""
    password_file = os.environ.get("PG8000_CANDIDATE_PASSWORD_FILE")
    if not password_file:
        raise RuntimeError("PG8000_CANDIDATE_PASSWORD_FILE is required")
    try:
        password = Path(password_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise RuntimeError("PG8000 candidate password file could not be read") from None
    if not password:
        raise RuntimeError("PG8000 candidate password file is empty")
    return password


def _connection() -> object:
    """Open one finite candidate connection from a private in-memory URI selector."""
    driver = _candidate_driver()
    parameters = dict(driver.parse_conninfo(_CREDENTIAL_FREE_DSN))
    parameters["password"] = _candidate_password()
    private_dsn = driver.make_conninfo(parameters)
    return driver.connect(private_dsn, connect_timeout_seconds=5)


def _run_command(arguments: list[str], *, timeout_seconds: int = 30) -> str:
    """Run one bounded local acceptance command with content-free failure output."""
    try:
        completed = subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        raise AssertionError("remote TLS acceptance command failed") from None
    return completed.stdout.strip()


def _candidate_container() -> str:
    """Return the CI-owned PostgreSQL container identity without guessing it."""
    container = os.environ.get("PG8000_CANDIDATE_CONTAINER")
    if not container:
        raise AssertionError("candidate PostgreSQL container identity is unavailable")
    return container


def _candidate_container_ip(container: str) -> str:
    """Resolve and validate the real non-loopback container address used for TLS."""
    address = _run_command(
        [
            "docker",
            "inspect",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container,
        ]
    )
    try:
        parsed = ip_address(address)
    except ValueError:
        raise AssertionError("candidate PostgreSQL container address is invalid") from None
    if parsed.is_loopback or parsed.is_unspecified:
        raise AssertionError("candidate PostgreSQL container address is not remote")
    return address


def _generate_ca(directory: Path, stem: str) -> tuple[Path, Path]:
    """Create one ephemeral CI-only certificate authority for TLS acceptance."""
    key_path = directory / f"{stem}.key"
    certificate_path = directory / f"{stem}.crt"
    _run_command(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-days",
            "1",
            "-subj",
            f"/CN={stem}",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-addext",
            "subjectKeyIdentifier=hash",
            "-keyout",
            str(key_path),
            "-out",
            str(certificate_path),
        ]
    )
    return key_path, certificate_path


def _generate_server_certificate(
    directory: Path,
    *,
    stem: str,
    ca_key: Path,
    ca_certificate: Path,
    identity_ip: str,
    serial: int,
) -> tuple[Path, Path]:
    """Create one ephemeral server certificate with an explicit IP SAN."""
    key_path = directory / f"{stem}.key"
    request_path = directory / f"{stem}.csr"
    certificate_path = directory / f"{stem}.crt"
    extension_path = directory / f"{stem}.ext"
    extension_path.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        f"subjectAltName=IP:{identity_ip}\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectKeyIdentifier=hash\n"
        "authorityKeyIdentifier=keyid:always,issuer\n",
        encoding="utf-8",
    )
    _run_command(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-subj",
            f"/CN={stem}",
            "-keyout",
            str(key_path),
            "-out",
            str(request_path),
        ]
    )
    _run_command(
        [
            "openssl",
            "x509",
            "-req",
            "-sha256",
            "-days",
            "1",
            "-in",
            str(request_path),
            "-CA",
            str(ca_certificate),
            "-CAkey",
            str(ca_key),
            "-set_serial",
            str(serial),
            "-extfile",
            str(extension_path),
            "-out",
            str(certificate_path),
        ]
    )
    return key_path, certificate_path


def _install_server_certificate(
    container: str,
    *,
    key_path: Path,
    certificate_path: Path,
) -> None:
    """Install a test-only server identity with PostgreSQL-required key ownership."""
    _run_command(
        ["docker", "exec", "--user", "0", container, "mkdir", "-p", _TLS_DIRECTORY]
    )
    _run_command(
        ["docker", "cp", str(key_path), f"{container}:{_TLS_DIRECTORY}/server.key"]
    )
    _run_command(
        [
            "docker",
            "cp",
            str(certificate_path),
            f"{container}:{_TLS_DIRECTORY}/server.crt",
        ]
    )
    _run_command(
        [
            "docker",
            "exec",
            "--user",
            "0",
            container,
            "chown",
            "postgres:postgres",
            f"{_TLS_DIRECTORY}/server.key",
            f"{_TLS_DIRECTORY}/server.crt",
        ]
    )
    _run_command(
        [
            "docker",
            "exec",
            "--user",
            "0",
            container,
            "chmod",
            "600",
            f"{_TLS_DIRECTORY}/server.key",
        ]
    )
    _run_command(
        [
            "docker",
            "exec",
            "--user",
            "0",
            container,
            "chmod",
            "644",
            f"{_TLS_DIRECTORY}/server.crt",
        ]
    )


def _alter_system(container: str, setting: str, value: str) -> None:
    """Set one bounded PostgreSQL server parameter through the CI superuser."""
    if setting not in {"ssl", "ssl_cert_file", "ssl_key_file"}:
        raise AssertionError("remote TLS acceptance setting is not admitted")
    literal = value.replace("'", "''")
    _run_command(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            _EXPECTED_USER,
            "-d",
            _EXPECTED_DATABASE,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f"ALTER SYSTEM SET {setting} = '{literal}'",
        ]
    )


def _restart_candidate_postgres(container: str) -> None:
    """Restart the disposable CI PostgreSQL and wait for its real readiness probe."""
    _run_command(["docker", "restart", container], timeout_seconds=60)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        completed = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "-U",
                _EXPECTED_USER,
                "-d",
                _EXPECTED_DATABASE,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode == 0:
            return
        time.sleep(0.5)
    raise AssertionError("candidate PostgreSQL did not become ready after TLS restart")


def _configure_server_tls(container: str, *, enabled: bool) -> None:
    """Enable or disable TLS on the disposable PostgreSQL test boundary."""
    if enabled:
        _alter_system(container, "ssl_cert_file", f"{_TLS_DIRECTORY}/server.crt")
        _alter_system(container, "ssl_key_file", f"{_TLS_DIRECTORY}/server.key")
    _alter_system(container, "ssl", "on" if enabled else "off")
    _restart_candidate_postgres(container)


@contextmanager
def _trusted_ca(certificate_path: Path) -> Iterator[None]:
    """Temporarily bind Python's default trust loading to one CI-only CA."""
    previous = os.environ.get("SSL_CERT_FILE")
    os.environ["SSL_CERT_FILE"] = str(certificate_path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SSL_CERT_FILE", None)
        else:
            os.environ["SSL_CERT_FILE"] = previous


def _remote_tls_driver(address: str, password: str) -> Pg8000DriverAdapter:
    """Construct the production adapter with a credential-free service selector."""
    def resolve_service(service_name: str) -> dict[str, str]:
        if service_name != "tls-acceptance":
            raise AssertionError("unexpected TLS acceptance service selector")
        return {
            "host": address,
            "port": "5432",
            "dbname": _EXPECTED_DATABASE,
            "user": _EXPECTED_USER,
            "password": password,
        }

    return Pg8000DriverAdapter(dbapi, service_resolver=resolve_service)


def _assert_remote_tls_failure(driver: Pg8000DriverAdapter, password: str) -> None:
    """Require the exact content-free package TLS failure on real PostgreSQL."""
    try:
        connection = driver.connect(
            "service=tls-acceptance",
            connect_timeout_seconds=5,
        )
    except Pg8000DriverTlsPolicyError as error:
        if str(error) != "PostgreSQL TLS policy is unavailable":
            raise AssertionError("remote TLS diagnostic contract changed") from None
        if error.__cause__ is not None:
            raise AssertionError("remote TLS failure retained a chained cause") from None
        rendered = f"{error!s}\n{error!r}"
        if password in rendered:
            raise AssertionError("TLS failure disclosed credential material") from None
        return
    except Exception:
        raise AssertionError(
            "remote PostgreSQL TLS failure escaped package policy boundary"
        ) from None
    connection.close()
    raise AssertionError("remote PostgreSQL TLS failure was accepted")


def _assert_production_remote_tls_contract() -> None:
    """Exercise authenticated TLS, peer identity, and no-downgrade on real PostgreSQL."""
    container = _candidate_container()
    address = _candidate_container_ip(container)
    password = _candidate_password()
    restored_plaintext = False

    with TemporaryDirectory(prefix="pg-llm-batch-tls-") as temporary_directory:
        directory = Path(temporary_directory)
        ca_key, ca_certificate = _generate_ca(directory, "pg-llm-batch-ci-ca")
        _, untrusted_ca_certificate = _generate_ca(
            directory,
            "pg-llm-batch-ci-untrusted-ca",
        )
        matching_key, matching_certificate = _generate_server_certificate(
            directory,
            stem="matching-server",
            ca_key=ca_key,
            ca_certificate=ca_certificate,
            identity_ip=address,
            serial=1001,
        )
        mismatch_key, mismatch_certificate = _generate_server_certificate(
            directory,
            stem="mismatch-server",
            ca_key=ca_key,
            ca_certificate=ca_certificate,
            identity_ip="192.0.2.1",
            serial=1002,
        )

        try:
            _install_server_certificate(
                container,
                key_path=matching_key,
                certificate_path=matching_certificate,
            )
            _configure_server_tls(container, enabled=True)
            driver = _remote_tls_driver(address, password)

            with _trusted_ca(ca_certificate):
                connection = driver.connect(
                    "service=tls-acceptance",
                    connect_timeout_seconds=5,
                )
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT ssl FROM pg_catalog.pg_stat_ssl "
                            "WHERE pid = pg_backend_pid()"
                        )
                        if cursor.fetchone() != (True,):
                            raise AssertionError("remote PostgreSQL connection is not TLS")
                finally:
                    connection.close()

            with _trusted_ca(untrusted_ca_certificate):
                _assert_remote_tls_failure(driver, password)

            _install_server_certificate(
                container,
                key_path=mismatch_key,
                certificate_path=mismatch_certificate,
            )
            _restart_candidate_postgres(container)
            with _trusted_ca(ca_certificate):
                _assert_remote_tls_failure(driver, password)

            _configure_server_tls(container, enabled=False)
            restored_plaintext = True
            with _trusted_ca(ca_certificate):
                _assert_remote_tls_failure(driver, password)
        finally:
            if not restored_plaintext:
                try:
                    _configure_server_tls(container, enabled=False)
                except AssertionError:
                    pass


def _assert_keyword_and_service_selector_connections() -> None:
    """Prove exact-artifact connection parity beyond the URI-only happy path.

    Unit tests establish grammar and precedence, but issue #322 requires the
    replacement to preserve the selectors used by deployed PostgreSQL clients.
    This probe therefore opens real PostgreSQL sessions through both the bounded
    keyword grammar and the explicit caller-selected service-file resolver. The
    temporary service file remains credential-free; the ephemeral password is
    injected by the trusted in-process resolver so it is never written to disk.
    """
    password = _candidate_password()
    keyword_driver = _candidate_driver()
    keyword_connection = keyword_driver.connect(
        "host=127.0.0.1 port=5432 dbname=pgllm user=pgllm "
        f"password={password}",
        connect_timeout_seconds=5,
    )
    try:
        with keyword_connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            if cursor.fetchone() != (_EXPECTED_DATABASE, _EXPECTED_USER):
                raise AssertionError("candidate keyword selector connection changed")
    finally:
        keyword_connection.close()

    service_file = Path(os.environ["PG8000_CANDIDATE_PASSWORD_FILE"]).with_name(
        "pg8000_candidate_service.conf"
    )
    service_file.write_text(
        "[candidate]\n"
        "host=127.0.0.1\n"
        "port=5432\n"
        "dbname=pgllm\n"
        "user=pgllm\n",
        encoding="utf-8",
    )
    try:
        file_resolver = Pg8000CandidateServiceFileResolver(service_file)

        def resolve_service(service_name: str) -> dict[str, str]:
            parameters = file_resolver(service_name)
            parameters["password"] = password
            return parameters

        service_driver = Pg8000CandidateDriverAdapter(
            dbapi,
            service_resolver=resolve_service,
        )
        service_connection = service_driver.connect(
            "service=candidate",
            connect_timeout_seconds=5,
        )
        try:
            with service_connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                if cursor.fetchone() != (_EXPECTED_DATABASE, _EXPECTED_USER):
                    raise AssertionError("candidate service selector connection changed")
        finally:
            service_connection.close()
    finally:
        service_file.unlink(missing_ok=True)


def _cleanup() -> None:
    """Remove candidate-only database objects even after a prior interrupted smoke."""
    connection = _connection()
    try:
        connection.set_autocommit(True)
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS pg8000_candidate_contract")
            cursor.execute("DROP ROLE IF EXISTS pg8000_candidate_reader")
    finally:
        connection.close()


def _assert_restore_catalog_inspection() -> None:
    """Prove the candidate can inspect the packaged restore catalog exactly.

    The production restore acceptance query binds finite Python lists through
    ``ANY(%s)`` and consumes catalog booleans and tuple rows. Running that exact
    query through pg8000 closes a driver-parity gap that unit adapters cannot
    prove, without turning the candidate into the production runtime.
    """
    connection = _connection()
    try:
        connection.set_autocommit(True)
        evidence = inspect_postgres_restore_catalog(connection)
        if evidence.required_table_count != 11:
            raise AssertionError("candidate restore catalog table evidence changed")
        if evidence.required_index_count != 2:
            raise AssertionError("candidate restore catalog index evidence changed")
        if evidence.lifecycle_rls_forced is not True:
            raise AssertionError("candidate restore catalog RLS evidence changed")
    finally:
        connection.close()


def _prepare_rls_fixture() -> tuple[uuid.UUID, datetime]:
    """Create an ephemeral RLS fixture and return exact typed evidence values."""
    evidence_uuid = uuid.uuid4()
    evidence_time = datetime.now(timezone.utc).replace(microsecond=0)
    connection = _connection()
    try:
        connection.set_autocommit(True)
        with connection.cursor() as cursor:
            cursor.execute("CREATE ROLE pg8000_candidate_reader NOLOGIN")
            cursor.execute(
                """
                CREATE TABLE pg8000_candidate_contract (
                    tenant_scope TEXT NOT NULL,
                    evidence_uuid UUID NOT NULL,
                    evidence_time TIMESTAMPTZ NOT NULL,
                    evidence_json JSONB NOT NULL
                )
                """
            )
            cursor.execute(
                "ALTER TABLE pg8000_candidate_contract ENABLE ROW LEVEL SECURITY"
            )
            cursor.execute(
                "ALTER TABLE pg8000_candidate_contract FORCE ROW LEVEL SECURITY"
            )
            cursor.execute(
                """
                CREATE POLICY candidate_tenant_scope ON pg8000_candidate_contract
                USING (
                    tenant_scope = current_setting(
                        'pg_llm_batch.tenant_scope', true
                    )
                )
                """
            )
            cursor.execute(
                "GRANT SELECT ON pg8000_candidate_contract TO pg8000_candidate_reader"
            )
            cursor.execute(
                """
                INSERT INTO pg8000_candidate_contract
                    (tenant_scope, evidence_uuid, evidence_time, evidence_json)
                VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)
                """,
                (
                    "tenant-a",
                    evidence_uuid,
                    evidence_time,
                    adapt_pg8000_jsonb({"candidate": "pg8000", "visible": True}),
                    "tenant-b",
                    uuid.uuid4(),
                    evidence_time,
                    adapt_pg8000_jsonb({"candidate": "pg8000", "visible": False}),
                ),
            )
            if cursor.row_count() != 2:
                raise AssertionError("pg8000 candidate row-count evidence is not exact")
    finally:
        connection.close()
    return evidence_uuid, evidence_time


def _assert_transaction_commit() -> None:
    """Prove a successful package connection context commits a real write."""
    connection = _connection()
    with connection as transaction:
        with transaction.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pg8000_candidate_contract
                SET evidence_json = %s
                WHERE tenant_scope = %s
                """,
                (adapt_pg8000_jsonb({"committed": True}), "tenant-b"),
            )
            if cursor.row_count() != 1:
                raise AssertionError("candidate commit probe did not update one row")

    verification = _connection()
    try:
        with verification.cursor() as cursor:
            cursor.execute(
                """
                SELECT evidence_json
                FROM pg8000_candidate_contract
                WHERE tenant_scope = %s
                """,
                ("tenant-b",),
            )
            if cursor.fetchone() != ({"committed": True},):
                raise AssertionError("candidate connection context did not commit")
    finally:
        verification.close()


def _assert_transaction_rollback() -> None:
    """Prove an exceptional package connection context rolls a real write back."""
    connection = _connection()
    try:
        with connection as transaction:
            with transaction.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE pg8000_candidate_contract
                    SET evidence_json = %s
                    WHERE tenant_scope = %s
                    """,
                    (adapt_pg8000_jsonb({"rolled_back": True}), "tenant-a"),
                )
                if cursor.row_count() != 1:
                    raise AssertionError("candidate rollback probe did not update one row")
                raise RuntimeError("candidate rollback probe")
    except RuntimeError as exc:
        if str(exc) != "candidate rollback probe":
            raise

    verification = _connection()
    try:
        with verification.cursor() as cursor:
            cursor.execute(
                """
                SELECT evidence_json
                FROM pg8000_candidate_contract
                WHERE tenant_scope = %s
                """,
                ("tenant-a",),
            )
            if cursor.fetchone() != ({"candidate": "pg8000", "visible": True},):
                raise AssertionError("candidate connection context did not roll back")
    finally:
        verification.close()


def _assert_undefined_function_classification() -> None:
    """Prove SQLSTATE-based undefined-function classification on real PostgreSQL."""
    driver = _candidate_driver()
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT pg_llm_batch_candidate_missing_function()")
            except BaseException as error:
                if not driver.is_undefined_function(error):
                    raise AssertionError(
                        "candidate undefined-function classification changed"
                    ) from error
            else:
                raise AssertionError("candidate undefined-function probe unexpectedly exists")
        connection.rollback()
    finally:
        connection.close()


def _assert_transport_failure_recovery() -> None:
    """Prove a severed candidate session is discarded and a fresh one recovers.

    The CI PostgreSQL user owns the ephemeral server and may terminate one of its
    own backends. The victim operation must surface the server-side disconnect;
    local close must then mark that capability terminal even if protocol cleanup
    itself reports the severed transport. Recovery authority is a newly opened
    connection, never reuse of the failed session.
    """
    victim = _connection()
    terminator = _connection()
    try:
        with victim.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            row = cursor.fetchone()
            if row is None or len(row) != 1 or type(row[0]) is not int:
                raise AssertionError("candidate backend identity evidence changed")
            backend_pid = row[0]

        terminator.set_autocommit(True)
        with terminator.cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(%s)", (backend_pid,))
            if cursor.fetchone() != (True,):
                raise AssertionError("candidate backend termination did not succeed")

        try:
            with victim.cursor() as cursor:
                cursor.execute("SELECT 1")
        except BaseException:
            pass
        else:
            raise AssertionError("candidate reused a server-terminated session")
    finally:
        terminator.close()
        try:
            victim.close()
        except BaseException:
            pass
        if not victim.is_closed():
            raise AssertionError("candidate failed connection did not become terminal")

    recovered = _connection()
    try:
        with recovered.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise AssertionError("candidate fresh-session recovery changed")
    finally:
        recovered.close()


def _assert_typed_rls_read(
    expected_uuid: uuid.UUID,
    expected_time: datetime,
) -> None:
    """Prove transaction-local tenant scope and typed result semantics together."""
    connection = _connection()
    with connection as transaction:
        with transaction.cursor() as cursor:
            cursor.execute("SET ROLE pg8000_candidate_reader")
            cursor.execute(
                "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
                ("tenant-a",),
            )
            cursor.execute(
                """
                SELECT tenant_scope, evidence_uuid, evidence_time, evidence_json
                FROM pg8000_candidate_contract
                ORDER BY tenant_scope
                """
            )
            rows = cursor.fetchmany(1)
            if len(rows) != 1:
                raise AssertionError("RLS candidate read exceeded one visible tenant row")
            tenant_scope, evidence_uuid, evidence_time, evidence_json = rows[0]
            if tenant_scope != "tenant-a":
                raise AssertionError("transaction-local tenant scope was not preserved")
            if evidence_uuid != expected_uuid:
                raise AssertionError("UUID adaptation changed candidate evidence")
            if evidence_time != expected_time:
                raise AssertionError("timestamp adaptation changed candidate evidence")
            if evidence_json != {"candidate": "pg8000", "visible": True}:
                raise AssertionError("JSONB adaptation changed candidate evidence")
            if cursor.fetchmany(1):
                raise AssertionError("RLS exposed another tenant through the candidate")


def main() -> None:
    """Run exact-artifact and real-PostgreSQL candidate acceptance probes."""
    if metadata.version("pg8000") != _EXPECTED_VERSION:
        raise AssertionError("unexpected pg8000 candidate version")
    _candidate_driver()
    _assert_keyword_and_service_selector_connections()

    connection = _connection()
    with connection as transaction:
        with transaction.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, %s::text", ("bound",))
            if cursor.fetchone() != (_EXPECTED_DATABASE, _EXPECTED_USER, "bound"):
                raise AssertionError("candidate parameter/result semantics changed")

    _assert_restore_catalog_inspection()
    _assert_undefined_function_classification()
    _assert_transport_failure_recovery()
    _cleanup()
    try:
        evidence_uuid, evidence_time = _prepare_rls_fixture()
        _assert_transaction_commit()
        _assert_transaction_rollback()
        _assert_typed_rls_read(evidence_uuid, evidence_time)
    finally:
        _cleanup()
    _assert_production_remote_tls_contract()


if __name__ == "__main__":
    main()
