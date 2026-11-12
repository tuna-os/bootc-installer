"""The phone companion server on a real socket (#306).

test_phone_companion.py checks the handler with stubs. These tests start the
real server on loopback, with a real certificate from openssl, and talk to it
over TLS: an idle TCP client used to block the form for everyone and freeze
stop(), and stubs cannot show that.
"""

import http.client
import json
import shutil
import socket
import ssl
import tempfile
import time

import pytest

from bootc_installer.utils import phone_companion
from bootc_installer.utils.phone_companion import CONFIG_RECEIVED_EVENT, CompanionServer

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")

_GOOD = {"fullname": "Ada Lovelace", "username": "ada", "password": "s3cret-pass", "hostname": "engine"}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def certs_in(tmp_path, monkeypatch):
    """Where mkdtemp puts the certificate directory during the test."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


@pytest.fixture
def server(certs_in):
    phone_companion.GLOBAL_CONFIG = None
    CONFIG_RECEIVED_EVENT.clear()
    srv = CompanionServer(port=_free_port(), host="127.0.0.1")
    assert srv.start() is True, srv.unavailable_reason
    yield srv
    srv.stop(wait=True)
    phone_companion.GLOBAL_CONFIG = None
    CONFIG_RECEIVED_EVENT.clear()


def _https(server, timeout=5):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # self-signed, as on the phone
    return http.client.HTTPSConnection(server.host, server.port, timeout=timeout, context=context)


def _get_form(server, timeout=5):
    conn = _https(server, timeout)
    try:
        conn.request("GET", "/?token=" + server.auth_token)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def _idle_client(server):
    """A TCP connection that never sends a byte: a browser's preconnect."""
    return socket.create_connection((server.host, server.port), timeout=5)


def test_the_form_is_served_over_tls(server):
    status, body = _get_form(server)
    assert status == 200
    assert b'id="password-confirm"' in body


def test_plain_http_gets_nothing(server):
    with socket.create_connection((server.host, server.port), timeout=5) as s:
        s.sendall(b"GET /?token=" + server.auth_token.encode() + b" HTTP/1.0\r\n\r\n")
        s.settimeout(5)
        try:
            data = s.recv(4096)
        except OSError:
            data = b""
    assert b"password" not in data and not data.startswith(b"HTTP/")


def test_an_idle_connection_does_not_block_the_form(server):
    """The reproduction from #306: with one silent client connected, a real
    GET failed with "handshake operation timed out"."""
    idle = [_idle_client(server) for _ in range(3)]
    try:
        time.sleep(0.2)  # let the server accept them
        started = time.monotonic()
        status, _body = _get_form(server, timeout=3)
        assert status == 200
        assert time.monotonic() - started < 2.0
    finally:
        for s in idle:
            s.close()


def test_stop_returns_while_an_idle_client_is_still_connected(server):
    """stop() used to hang until the idle client went away, and it ran on the
    GTK main thread: Skip or Back froze the window."""
    idle = _idle_client(server)
    try:
        time.sleep(0.2)
        port = server.port
        started = time.monotonic()
        stopper = server.stop()
        assert time.monotonic() - started < 0.5, "stop() waited on the main thread"
        stopper.join(3)
        assert not stopper.is_alive(), "the server never shut down"
        # The listening socket is closed: nothing accepts on the port now.
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
    finally:
        idle.close()


def test_a_silent_client_is_dropped_after_the_handshake_timeout(server, monkeypatch):
    monkeypatch.setattr(phone_companion, "HANDSHAKE_TIMEOUT", 0.3)
    idle = _idle_client(server)
    try:
        idle.settimeout(5)
        started = time.monotonic()
        assert idle.recv(1) == b"", "the server should close the connection"
        assert time.monotonic() - started < 3.0
    finally:
        idle.close()


def test_connections_over_the_cap_are_closed_at_accept(server, monkeypatch):
    """Each connection holds a thread until it finishes or times out; a LAN
    client must not be able to open them without limit."""
    idle = [_idle_client(server) for _ in range(phone_companion.MAX_CONNECTIONS)]
    try:
        time.sleep(0.3)
        extra = _idle_client(server)
        try:
            extra.settimeout(3)
            assert extra.recv(1) == b""
        finally:
            extra.close()
    finally:
        for s in idle:
            s.close()


def test_the_server_binds_only_the_advertised_address(server):
    assert server.server.server_address == ("127.0.0.1", server.port)


def test_the_private_key_does_not_stay_on_disk(certs_in, server):
    """#306: the certificate directory used to stay in /tmp for good. It is
    gone as soon as the pair is loaded, and it is still gone after stop."""
    assert _get_form(server)[0] == 200  # TLS works without the files
    assert [p.name for p in certs_in.iterdir()] == []
    server.stop(wait=True)
    assert [p.name for p in certs_in.iterdir()] == []


def test_a_failed_certificate_leaves_no_directory(certs_in, monkeypatch):
    from tests.unit.fake_host import MISSING, FakeExecutor

    assert phone_companion.generate_self_signed_cert(FakeExecutor([MISSING])) is None
    assert list(certs_in.iterdir()) == []


def test_submit_once_and_the_token_dies(server):
    token = server.auth_token
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    conn = _https(server)
    conn.request("POST", "/api/config", body=json.dumps(_GOOD), headers=headers)
    response = conn.getresponse()
    assert response.status == 200 and json.loads(response.read()) == {"status": "success"}
    conn.close()
    assert CONFIG_RECEIVED_EVENT.is_set()
    assert server.get_config() == _GOOD

    conn = _https(server)
    conn.request("POST", "/api/config", body=json.dumps({**_GOOD, "username": "intruder"}), headers=headers)
    assert conn.getresponse().status == 403
    conn.close()
    assert server.get_config()["username"] == "ada"


def test_the_port_is_free_again_for_the_next_visit(certs_in):
    """Back and forward again: start() waits for the last stop(), which is
    still closing the socket on its own thread."""
    port = _free_port()
    for _ in range(3):
        srv = CompanionServer(port=port, host="127.0.0.1")
        assert srv.start() is True, srv.unavailable_reason
        assert _get_form(srv)[0] == 200
        srv.stop()  # no wait: the next start() has to cope


def test_stop_twice_is_harmless(server):
    assert server.stop(wait=True) is not None
    assert server.stop() is None
