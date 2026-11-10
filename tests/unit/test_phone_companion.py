import io
import json
import re
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from bootc_installer.utils import phone_companion
from bootc_installer.utils.phone_companion import (
    COMPANION_HTML,
    render_companion_html,
    CONFIG_RECEIVED_EVENT,
    CompanionRequestHandler,
    CompanionServer,
    generate_self_signed_cert,
    get_local_ip,
)


@pytest.fixture(autouse=True)
def reset_phone_companion_state():
    phone_companion.GLOBAL_CONFIG = None
    CONFIG_RECEIVED_EVENT.clear()
    yield
    phone_companion.GLOBAL_CONFIG = None
    CONFIG_RECEIVED_EVENT.clear()


def _make_handler(path, body=b"", token="test-token", auth=None):
    handler = CompanionRequestHandler.__new__(CompanionRequestHandler)
    handler.path = path
    handler.server = MagicMock(auth_token=token)
    handler.headers = {"Content-Length": str(len(body))}
    if auth is not None:
        handler.headers["Authorization"] = auth
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.send_error = MagicMock()
    return handler


def test_get_local_ip_returns_socket_address():
    sock = MagicMock()
    sock.getsockname.return_value = ("192.168.1.25", 12345)

    with patch("bootc_installer.utils.phone_companion.socket.socket", return_value=sock):
        assert get_local_ip() == "192.168.1.25"

    sock.connect.assert_called_once_with(("8.8.8.8", 80))
    sock.close.assert_called_once_with()


def test_get_local_ip_falls_back_to_hostname_lookup_on_udp_failure():
    with patch("bootc_installer.utils.phone_companion.socket.socket", side_effect=OSError("offline")), \
         patch("bootc_installer.utils.phone_companion.socket.gethostname", return_value="installer"), \
         patch("bootc_installer.utils.phone_companion.socket.gethostbyname", return_value="10.0.0.9"):
        assert get_local_ip() == "10.0.0.9"


def test_get_local_ip_is_none_when_all_lookups_fail():
    """#306: no route means no address, not 127.0.0.1. A QR code for
    loopback opens nothing on a phone."""
    with patch("bootc_installer.utils.phone_companion.socket.socket", side_effect=OSError("offline")), \
         patch("bootc_installer.utils.phone_companion.socket.gethostbyname", side_effect=OSError("no dns")):
        assert get_local_ip() is None


@pytest.mark.parametrize("address", ["127.0.0.1", "127.0.1.1", "0.0.0.0", "169.254.7.7", "not-an-ip"])
def test_get_local_ip_refuses_an_address_no_phone_can_reach(address):
    """Debian resolves the host's own name to 127.0.1.1; that is not a LAN
    address either."""
    with patch("bootc_installer.utils.phone_companion.socket.socket", side_effect=OSError("offline")), \
         patch("bootc_installer.utils.phone_companion.socket.gethostbyname", return_value=address):
        assert get_local_ip() is None


def test_generate_self_signed_cert_runs_openssl_into_a_private_dir():
    import os
    import stat

    with patch("bootc_installer.utils.phone_companion.subprocess.run") as run_mock:
        cert, key = generate_self_signed_cert()

    certdir = os.path.dirname(cert)
    assert os.path.dirname(key) == certdir
    assert not certdir.startswith("/tmp/companion")
    # mkdtemp: only this user can read the key or plant files in its place.
    assert stat.S_IMODE(os.stat(certdir).st_mode) == 0o700
    run_mock.assert_called_once_with(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key,
            "-out", cert,
            "-days", "1", "-nodes",
            "-subj", "/CN=bootc-companion",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_generate_self_signed_cert_returns_false_on_failure():
    with patch(
        "bootc_installer.utils.phone_companion.subprocess.run",
        side_effect=OSError("openssl missing"),
    ), patch("bootc_installer.utils.phone_companion.logger.warning") as warning_mock:
        assert generate_self_signed_cert() is None

    warning_mock.assert_called_once()


def test_companion_server_init_sets_default_state():
    server = CompanionServer()

    assert server.port == 8443
    assert server.server is None
    assert server.thread is None
    assert server.is_https is False
    assert server.auth_token is None


def test_companion_server_never_serves_plain_http():
    """#185: without a certificate the server does not start at all; the
    password must not cross the LAN in clear text."""
    server = CompanionServer(port=9999)
    phone_companion.GLOBAL_CONFIG = {"stale": True}
    CONFIG_RECEIVED_EVENT.set()

    with patch("bootc_installer.utils.phone_companion.generate_self_signed_cert", return_value=None), \
         patch("bootc_installer.utils.phone_companion.http.server.HTTPServer") as http_server_mock:
        assert server.start() is False

    http_server_mock.assert_not_called()
    assert server.server is None
    assert server.is_https is False
    assert server.auth_token is None
    assert phone_companion.GLOBAL_CONFIG is None
    assert not CONFIG_RECEIVED_EVENT.is_set()


def test_companion_server_start_binds_the_advertised_address_and_keeps_tls_per_connection():
    """#306: the server binds the one address the QR code names (not
    0.0.0.0), is threaded, and leaves the listening socket plain: the TLS
    handshake belongs to each connection's own thread."""
    server = CompanionServer(port=8443)
    fake_server = MagicMock()
    listening_socket = fake_server.socket
    ssl_context = MagicMock()

    fake_thread = MagicMock()
    with patch("bootc_installer.utils.phone_companion.get_local_ip", return_value="192.0.2.44"), \
         patch("bootc_installer.utils.phone_companion.generate_self_signed_cert",
               return_value=("/priv/cert.pem", "/priv/key.pem")), \
         patch("bootc_installer.utils.phone_companion._CompanionHTTPServer", return_value=fake_server) as http_server_mock, \
         patch("bootc_installer.utils.phone_companion.ssl.SSLContext", return_value=ssl_context) as ssl_context_cls, \
         patch("bootc_installer.utils.phone_companion.threading.Thread", return_value=fake_thread) as thread_mock:
        assert server.start() is True

    assert server.is_https is True
    assert server.host == "192.0.2.44"
    assert server.auth_token is not None
    assert fake_server.auth_token == server.auth_token
    http_server_mock.assert_called_once_with(("192.0.2.44", 8443), CompanionRequestHandler)
    thread_mock.assert_called_once_with(
        target=fake_server.serve_forever,
        kwargs={"poll_interval": phone_companion._POLL_INTERVAL}, daemon=True)
    fake_thread.start.assert_called_once_with()
    ssl_context_cls.assert_called_once_with(phone_companion.ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain.assert_called_once_with(
        certfile="/priv/cert.pem",
        keyfile="/priv/key.pem",
    )
    ssl_context.wrap_socket.assert_not_called()
    assert fake_server.socket is listening_socket
    assert fake_server.ssl_context is ssl_context


def test_the_real_server_class_is_threaded_with_daemon_threads():
    import socketserver

    assert issubclass(phone_companion._CompanionHTTPServer, socketserver.ThreadingMixIn)
    assert phone_companion._CompanionHTTPServer.daemon_threads is True
    assert CompanionRequestHandler.timeout == phone_companion.SOCKET_TIMEOUT


def test_companion_server_is_unavailable_without_a_route():
    """#306: no LAN address: no server, no certificate, and a reason the
    page can show."""
    server = CompanionServer()
    with patch("bootc_installer.utils.phone_companion.get_local_ip", return_value=None), \
         patch("bootc_installer.utils.phone_companion.generate_self_signed_cert") as cert_mock, \
         patch("bootc_installer.utils.phone_companion._CompanionHTTPServer") as http_server_mock:
        assert server.start() is False

    cert_mock.assert_not_called()
    http_server_mock.assert_not_called()
    assert server.unavailable_reason == CompanionServer.NO_NETWORK
    assert server.auth_token is None


def test_companion_server_stop_shuts_down_active_server():
    server = CompanionServer()
    fake_server = MagicMock()
    server.server = fake_server
    server.auth_token = "live"

    server.stop(wait=True)

    fake_server.shutdown.assert_called_once_with()
    fake_server.server_close.assert_called_once_with()
    assert fake_server.auth_token is None
    assert server.server is None
    assert server.auth_token is None


def test_companion_server_stop_does_not_wait_for_shutdown():
    """#306: stop() is called on the GTK main thread. shutdown() can take as
    long as it likes; stop() has returned, and the token is already dead."""
    import threading
    import time

    release = threading.Event()
    fake_server = MagicMock()
    fake_server.shutdown.side_effect = lambda: release.wait(10)
    server = CompanionServer()
    server.server = fake_server
    server.auth_token = "live"

    started = time.monotonic()
    stopper = server.stop()
    elapsed = time.monotonic() - started
    try:
        assert elapsed < 1.0
        assert stopper is not threading.current_thread() and stopper.is_alive()
        assert stopper.daemon
        assert fake_server.auth_token is None and server.auth_token is None
        fake_server.server_close.assert_not_called()
    finally:
        release.set()
        stopper.join(5)
    fake_server.server_close.assert_called_once_with()


def test_companion_server_get_config_returns_current_global_config():
    server = CompanionServer()

    assert server.get_config() is None

    phone_companion.GLOBAL_CONFIG = {"hostname": "bluefin"}

    assert server.get_config() == {"hostname": "bluefin"}


def test_handler_get_root_serves_html():
    handler = _make_handler("/?token=test-token")

    handler.do_GET()

    handler.send_response.assert_called_once_with(200)
    raw = handler.wfile.getvalue()
    assert handler.send_header.call_args_list == [
        call("Content-Type", "text/html; charset=utf-8"),
        call("Cache-Control", "no-store"),
        call("Referrer-Policy", "no-referrer"),
        call("Content-Length", str(len(raw))),
    ]
    handler.end_headers.assert_called_once_with()
    body = raw.decode("utf-8")
    assert body == render_companion_html()
    # The served page names the branded product, never a placeholder or a
    # hardcoded distro.
    assert not re.search(r"__[A-Z_]+__", body), "a placeholder reached the phone"
    assert "Bluefin" not in body
    assert "__T_TITLE__" in COMPANION_HTML and "__T_HEADING__" in COMPANION_HTML


def test_render_companion_html_fills_branding():
    body = render_companion_html(name="Marlin", hostname="reef")
    assert "<title>Marlin Installer Companion</title>" in body
    assert "<h1>Marlin Setup</h1>" in body
    assert 'value="reef-desktop"' in body


def test_render_companion_html_escapes_the_branding():
    """The name comes from a file on the host; it must not become markup."""
    body = render_companion_html(name='<script>x</script>"', hostname='a"b')
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;x&lt;/script&gt;&quot;" in body
    assert 'value="a&quot;b-desktop"' in body


def test_the_form_has_no_ssh_key_field():
    """#305: the recipe has no SSH field, so the form must not ask for a key
    it would then drop."""
    body = render_companion_html(name="Marlin", hostname="reef")
    assert "ssh" not in body.lower()


def test_the_form_confirms_the_password_and_can_reveal_it():
    """#306: a password typed blind on a phone is typed twice, and one
    switch shows both fields."""
    body = render_companion_html(name="Marlin", hostname="reef")
    assert body.count('type="password"') == 2
    assert 'id="password-confirm"' in body and 'for="password-confirm"' in body
    assert '<input type="checkbox" id="reveal">' in body
    assert "password.value === confirmation.value" in body
    assert "T.err_mismatch" in body and '"err_mismatch": "The passwords do not match."' in body
    # The mismatch check runs before anything is sent.
    assert body.index("T.err_mismatch") < body.index("fetch('/api/config'")
    # The confirmation is the phone's business: it is not posted.
    payload = body[body.index("const payload = {"):body.index("};", body.index("const payload = {"))]
    assert "confirm" not in payload


def test_the_form_is_translated_through_gettext():
    """#311: the phone form was English only."""
    def fake(text):
        return {"Full Name": "Vollständiger <Name>",
                "The passwords do not match.": 'Passwörter "ungleich" </script>'}.get(text, text)

    with patch("bootc_installer.utils.phone_companion._", side_effect=fake):
        body = render_companion_html(name="Marlin", hostname="reef")
    assert '<label for="fullname">Vollständiger &lt;Name&gt;</label>' in body
    assert "Full Name" not in body
    script = body[body.index("const T = "):]
    assert '\\"ungleich\\"' in script.split("\n")[0]
    assert "</script>" not in script.split("\n")[0]


def test_handler_does_not_expose_current_config():
    phone_companion.GLOBAL_CONFIG = {"hostname": "bluefin", "username": "jorge"}
    handler = _make_handler("/config?token=test-token")

    handler.do_GET()

    handler.send_error.assert_called_once_with(404, "Not Found")


def test_handler_get_unknown_path_returns_404():
    handler = _make_handler("/missing?token=test-token")

    handler.do_GET()

    handler.send_error.assert_called_once_with(404, "Not Found")


def test_handler_post_valid_config_updates_global_state_and_event():
    payload = {
        "fullname": "John Doe",
        "username": "johndoe",
        "password": "secret",
        "hostname": "bluefin",
    }
    handler = _make_handler("/api/config", json.dumps(payload).encode("utf-8"), auth="Bearer test-token")

    handler.do_POST()

    assert phone_companion.GLOBAL_CONFIG == payload
    assert CONFIG_RECEIVED_EVENT.is_set()
    handler.send_response.assert_called_once_with(200)
    assert handler.send_header.call_args_list == [
        call("Content-Type", "application/json"),
        call("Content-Length", str(len(handler.wfile.getvalue()))),
    ]
    assert json.loads(handler.wfile.getvalue().decode("utf-8")) == {"status": "success"}


def test_handler_post_invalid_json_returns_error_without_setting_state():
    handler = _make_handler("/api/config", b"{not-json", auth="Bearer test-token")

    with patch("bootc_installer.utils.phone_companion.logger.error") as error_mock:
        handler.do_POST()

    assert phone_companion.GLOBAL_CONFIG is None
    assert not CONFIG_RECEIVED_EVENT.is_set()
    handler.send_response.assert_called_once_with(400)
    assert json.loads(handler.wfile.getvalue().decode("utf-8")) == {"status": "error"}
    error_mock.assert_called_once()


def test_handler_post_unknown_path_returns_404():
    handler = _make_handler("/api/other", b"{}", auth="Bearer test-token")

    handler.do_POST()

    handler.send_error.assert_called_once_with(404, "Not Found")


@pytest.mark.parametrize("method", ["do_GET", "do_POST"])
def test_handler_rejects_missing_or_invalid_token(method):
    handler = _make_handler("/api/config?token=wrong", b"{}", auth="Bearer wrong")

    getattr(handler, method)()

    handler.send_error.assert_called_once_with(403, "Forbidden")
    assert phone_companion.GLOBAL_CONFIG is None
    assert not CONFIG_RECEIVED_EVENT.is_set()


def test_handler_rejects_oversized_config():
    handler = _make_handler("/api/config", b"x" * (64 * 1024 + 1), auth="Bearer test-token")

    handler.do_POST()

    handler.send_error.assert_called_once_with(413, "Request body too large")
    assert phone_companion.GLOBAL_CONFIG is None


# ── #185: what a submission may contain ─────────────────────────────────────

_GOOD = {
    "fullname": "John Doe",
    "username": "johndoe",
    "password": "secret",
    "hostname": "Bluefin",
}


def _post(payload):
    handler = _make_handler("/api/config", json.dumps(payload).encode("utf-8"), auth="Bearer test-token")
    with patch("bootc_installer.utils.phone_companion.logger.error"):
        handler.do_POST()
    return handler


def test_sanitize_keeps_known_fields_and_normalises_hostname():
    from bootc_installer.utils.phone_companion import sanitize_config

    got = sanitize_config({**_GOOD, "extra": "dropped", "groups": ["wheel"]})
    assert got == {**_GOOD, "hostname": "bluefin"}


@pytest.mark.parametrize("bad", [
    {**_GOOD, "password": ["not", "a", "string"]},
    {**_GOOD, "hostname": "bad host; rm -rf /"},
    {**_GOOD, "hostname": "-leading-hyphen"},
    {**_GOOD, "hostname": "a" * 64},
    {**_GOOD, "username": "Root User"},
    {**_GOOD, "username": "0starts-with-digit"},
    {**_GOOD, "fullname": ""},
    {**_GOOD, "fullname": "x" * 257},
    {k: v for k, v in _GOOD.items() if k != "password"},
    ["not", "an", "object"],
])
def test_invalid_submission_is_rejected_and_not_stored(bad):
    handler = _post(bad)

    handler.send_response.assert_called_once_with(400)
    assert phone_companion.GLOBAL_CONFIG is None
    assert not CONFIG_RECEIVED_EVENT.is_set()


def test_a_posted_ssh_key_is_dropped():
    """#305: no recipe field takes an SSH key, so one from an old page or a
    hand-made request goes nowhere."""
    handler = _post({**_GOOD, "sshkey": "ssh-ed25519 AAA"})

    handler.send_response.assert_called_once_with(200)
    assert "sshkey" not in phone_companion.GLOBAL_CONFIG
    assert set(phone_companion.GLOBAL_CONFIG) == {"fullname", "username", "password", "hostname"}


def test_only_the_first_submission_is_accepted():
    """The page stops the server after the first config; a second POST in
    that window must not replace the account the user just sent."""
    _post(_GOOD)
    second = _post({**_GOOD, "username": "intruder"})

    second.send_error.assert_called_once_with(409, "Configuration already received")
    assert phone_companion.GLOBAL_CONFIG["username"] == "johndoe"


# ── #227: where the session token travels ───────────────────────────────────

def test_post_rejects_a_token_in_the_url():
    """The submission must carry the token in a header: a token in the query
    string is not accepted, so it is never repeated in a request line."""
    handler = _make_handler("/api/config?token=test-token", json.dumps(_GOOD).encode("utf-8"))

    handler.do_POST()

    handler.send_error.assert_called_once_with(403, "Forbidden")
    assert phone_companion.GLOBAL_CONFIG is None
    assert not CONFIG_RECEIVED_EVENT.is_set()


@pytest.mark.parametrize("auth", ["test-token", "Basic test-token", "Bearer", "Bearer wrong", ""])
def test_post_rejects_a_malformed_or_wrong_authorization_header(auth):
    handler = _make_handler("/api/config", json.dumps(_GOOD).encode("utf-8"), auth=auth)

    handler.do_POST()

    handler.send_error.assert_called_once_with(403, "Forbidden")
    assert phone_companion.GLOBAL_CONFIG is None


def test_bearer_scheme_is_case_insensitive():
    handler = _make_handler("/api/config", json.dumps(_GOOD).encode("utf-8"), auth="bearer test-token")

    handler.do_POST()

    handler.send_response.assert_called_once_with(200)


def test_token_is_single_use_after_an_accepted_submission():
    """Once the details are in, the QR code or a copy of its link opens
    nothing: the server forgets the token."""
    first = _make_handler("/api/config", json.dumps(_GOOD).encode("utf-8"), auth="Bearer test-token")
    first.do_POST()
    first.send_response.assert_called_once_with(200)
    assert first.server.auth_token is None

    again = _make_handler("/?token=test-token")
    again.server = first.server
    again.do_GET()
    again.send_error.assert_called_once_with(403, "Forbidden")


def test_rejected_submission_keeps_the_token():
    """A typo on the phone must not lock the user out of retrying."""
    handler = _make_handler("/api/config", b"{not-json", auth="Bearer test-token")
    with patch("bootc_installer.utils.phone_companion.logger.error"):
        handler.do_POST()

    assert handler.server.auth_token == "test-token"


def test_page_sends_the_token_in_a_header_and_drops_it_from_the_url():
    assert "'Authorization': 'Bearer ' + companionToken" in COMPANION_HTML
    assert "window.history.replaceState(null, '', window.location.pathname)" in COMPANION_HTML
    assert "/api/config?token=" not in COMPANION_HTML
