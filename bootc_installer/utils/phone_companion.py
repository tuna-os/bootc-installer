"""The phone companion's HTTPS server and the form it serves.

The form carries the account password, so the server is HTTPS only, binds to
the one address the QR code advertises, and answers each connection on its
own daemon thread with a handshake timeout and a socket timeout: a client
that connects and says nothing cannot block the form or the installer (#306).
"""

import html
import http.server
import ipaddress
import ssl
import socket
import threading
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from gettext import gettext as _
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("Installer::PhoneCompanion")

GLOBAL_CONFIG = None
CONFIG_RECEIVED_EVENT = threading.Event()
_CONFIG_LOCK = threading.Lock()
MAX_CONFIG_BYTES = 64 * 1024

# What the companion form may set, and how long each value may be. Anything
# else in the payload is dropped (#185): the values go straight into GTK
# entries and the install recipe, so a non-string or an unexpected key must
# not reach them. There is no SSH key field: the recipe has nowhere to put one
# (#305), so the form does not ask for it and a posted one is dropped.
_FIELD_LIMITS = {
    "fullname": 256,
    "username": 32,
    "password": 4096,
    "hostname": 63,
}
_REQUIRED_FIELDS = ("fullname", "username", "password", "hostname")
# The same rules the installer applies to typed input: user.py for the
# username, Systeminfo hostname generation for the hostname.
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def sanitize_config(raw):
    """The companion payload reduced to known string fields, or None.

    None means reject the submission: a required field is missing or empty,
    a value is not a string or is too long, or the username or hostname is
    not one the installer would accept if typed.
    """
    if not isinstance(raw, dict):
        return None
    config = {}
    for key, limit in _FIELD_LIMITS.items():
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value) > limit:
            return None
        config[key] = value
    config["hostname"] = config["hostname"].strip().lower()
    config["username"] = config["username"].strip()
    if any(not config[key] for key in _REQUIRED_FIELDS):
        return None
    if not _USERNAME_RE.match(config["username"]):
        return None
    if not _HOSTNAME_RE.match(config["hostname"]):
        return None
    return config

# Seconds a client has to finish the TLS handshake, and to send or take each
# piece of a request after it. A phone on the same LAN needs a fraction of it.
HANDSHAKE_TIMEOUT = 5
SOCKET_TIMEOUT = 10
# Connections served at once; more are closed at accept. The form is for one
# phone, and each connection holds a thread until it finishes or times out.
MAX_CONNECTIONS = 16
# serve_forever looks for a shutdown request this often, so stop() is quick.
_POLL_INTERVAL = 0.1


def _usable_lan_address(ip):
    """`ip` when a phone on the LAN could reach it, else None."""
    try:
        addr = ipaddress.ip_address(ip)
    except (TypeError, ValueError):
        return None
    if addr.is_loopback or addr.is_unspecified or addr.is_link_local or addr.is_multicast:
        return None
    return str(addr)


def get_local_ip():
    """The LAN address of the interface that has the default route, or None.

    None means no phone can reach this computer: there is no route, or the
    only address is loopback. The caller shows the "unavailable" page; a QR
    code for 127.0.0.1 opens nothing on a phone (#306).
    """
    try:
        # A UDP connect sends nothing; it only makes the kernel pick a route.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        # No default route. A LAN without a gateway can still resolve the
        # host's own name to its LAN address.
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            return None
    return _usable_lan_address(ip)


def _companion_strings():
    """Every line of the phone form, translated like the rest of the UI.

    `{name}` is the product name and `{hostname}` the default hostname stem,
    both from the branding contract.
    """
    return {
        "title": _("{name} Installer Companion"),
        "heading": _("{name} Setup"),
        "subtitle": _("Complete your installation settings from your phone"),
        "fullname": _("Full Name"),
        "fullname_hint": _("e.g. John Doe"),
        "username": _("Username"),
        "username_hint": _("e.g. johndoe"),
        "password": _("Password"),
        "password_hint": _("Create user password"),
        "confirm": _("Confirm Password"),
        "confirm_hint": _("Type the password again"),
        "reveal": _("Show passwords"),
        "hostname": _("Hostname"),
        "hostname_hint": _("e.g. {hostname}-desktop"),
        "submit": _("Submit Setup"),
        "done_title": _("Setup Completed!"),
        "done_body": _("You can now look back at the installer screen to confirm "
                       "and finish the installation."),
        "err_required": _("Please fill out all required fields."),
        "err_mismatch": _("The passwords do not match."),
        "err_rejected": _("Submission failed, please try again."),
        "err_connection": _("Connection error."),
    }


def render_companion_html(name=None, hostname=None):
    """COMPANION_HTML with the product name and hostname stem filled in from
    the branding contract (shared/branding/README.md); never a literal.

    Every value is escaped for where it lands: HTML for the markup, JSON for
    the script. The name comes from a file on the host, and a translation can
    hold any character.
    """
    if name is None or hostname is None:
        from bootc_shared import branding
        b = branding.resolve()
        name = name or b.name
        hostname = hostname or b.default_hostname
    strings = {
        key: text.replace("{name}", name).replace("{hostname}", hostname)
        for key, text in _companion_strings().items()
    }
    page = COMPANION_HTML
    for key, text in strings.items():
        page = page.replace("__T_%s__" % key.upper(), html.escape(text, quote=True))
    script_strings = json.dumps(
        {k: v for k, v in strings.items() if k.startswith("err_")}
    ).replace("</", "<\\/")
    return (page.replace("__JS_STRINGS__", script_strings)
            .replace("__HOSTNAME__", html.escape(hostname, quote=True)))


# Premium Dark-Mode HTML Form to serve on mobile devices
COMPANION_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>__T_TITLE__</title>
    <style>
        :root {
            --bg-color: #0b0b0f;
            --card-bg: rgba(26, 26, 36, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-color: #f3f4f6;
            --text-dim: #9ca3af;
            --primary: #3b82f6;
            --primary-glow: rgba(59, 130, 246, 0.5);
            --success: #10b981;
            --danger: #f87171;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }

        .container {
            width: 100%;
            max-width: 440px;
            padding: 24px;
            box-sizing: border-box;
        }

        .card {
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 32px 24px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            text-align: center;
            position: relative;
            overflow: hidden;
        }

        .card::before {
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            background: linear-gradient(135deg, var(--primary), transparent, transparent);
            border-radius: 24px;
            z-index: -1;
            opacity: 0.3;
        }

        h1 {
            font-size: 24px;
            margin: 0 0 8px 0;
            font-weight: 700;
        }

        p.subtitle {
            color: var(--text-dim);
            font-size: 14px;
            margin: 0 0 28px 0;
        }

        .form-group {
            text-align: left;
            margin-bottom: 20px;
        }

        label {
            display: block;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 6px;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        input, textarea {
            width: 100%;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px 16px;
            box-sizing: border-box;
            color: var(--text-color);
            font-size: 15px;
            transition: all 0.2s ease;
        }

        input:focus, textarea:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 8px var(--primary-glow);
        }

        button {
            width: 100%;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 12px;
            padding: 14px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 10px;
            transition: all 0.2s ease;
        }

        button:active {
            transform: scale(0.98);
        }

        #success-state {
            display: none;
        }

        .success-icon {
            font-size: 48px;
            color: var(--success);
            margin-bottom: 16px;
        }

        .reveal {
            display: flex;
            align-items: center;
            gap: 10px;
            text-transform: none;
            letter-spacing: 0;
            font-size: 14px;
            font-weight: 400;
        }

        .reveal input {
            width: 20px;
            height: 20px;
            flex: none;
        }

        input.invalid {
            border-color: var(--danger);
        }

        #form-error {
            color: var(--danger);
            font-size: 14px;
            min-height: 20px;
            margin: 0 0 4px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <form class="card" id="form-state" novalidate>
            <h1>__T_HEADING__</h1>
            <p class="subtitle">__T_SUBTITLE__</p>

            <div class="form-group">
                <label for="fullname">__T_FULLNAME__</label>
                <input type="text" id="fullname" autocomplete="name" placeholder="__T_FULLNAME_HINT__" required>
            </div>

            <div class="form-group">
                <label for="username">__T_USERNAME__</label>
                <input type="text" id="username" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="__T_USERNAME_HINT__" required>
            </div>

            <div class="form-group">
                <label for="password">__T_PASSWORD__</label>
                <input type="password" id="password" autocomplete="new-password" placeholder="__T_PASSWORD_HINT__" required>
            </div>

            <div class="form-group">
                <label for="password-confirm">__T_CONFIRM__</label>
                <input type="password" id="password-confirm" autocomplete="new-password" placeholder="__T_CONFIRM_HINT__" required>
            </div>

            <div class="form-group">
                <label class="reveal" for="reveal">
                    <input type="checkbox" id="reveal">
                    <span>__T_REVEAL__</span>
                </label>
            </div>

            <div class="form-group">
                <label for="hostname">__T_HOSTNAME__</label>
                <input type="text" id="hostname" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="__T_HOSTNAME_HINT__" value="__HOSTNAME__-desktop" required>
            </div>

            <p id="form-error" role="alert" aria-live="assertive"></p>
            <button type="submit">__T_SUBMIT__</button>
        </form>

        <div class="card" id="success-state">
            <div class="success-icon">✓</div>
            <h1>__T_DONE_TITLE__</h1>
            <p class="subtitle">__T_DONE_BODY__</p>
        </div>
    </div>

    <script>
        const T = __JS_STRINGS__;

        // The QR code carries the session token in ?token= so the page itself
        // can be fetched. Keep it in memory only and drop it from the address
        // bar and this history entry, so it does not linger in the phone's
        // browser history; the submission sends it in a header, not a URL
        // (#227). Scan the QR code again to reopen the form.
        const companionToken = new URLSearchParams(window.location.search).get('token') || '';
        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, '', window.location.pathname);
        }

        const field = id => document.getElementById(id);
        const password = field('password');
        const confirmation = field('password-confirm');
        const formError = field('form-error');

        // Auto-suggest username from full name
        field('fullname').addEventListener('input', function(e) {
            const name = e.target.value.toLowerCase();
            field('username').value = name.replace(/[^a-z0-9]/g, '');
        });

        // One switch shows or hides both password fields.
        field('reveal').addEventListener('change', function(e) {
            const type = e.target.checked ? 'text' : 'password';
            password.type = type;
            confirmation.type = type;
        });

        function passwordsMatch() {
            const ok = password.value === confirmation.value;
            confirmation.classList.toggle('invalid', !ok && confirmation.value !== '');
            return ok;
        }
        password.addEventListener('input', passwordsMatch);
        confirmation.addEventListener('input', function() {
            if (passwordsMatch()) { formError.textContent = ''; }
        });

        field('form-state').addEventListener('submit', function(e) {
            e.preventDefault();
            submitConfig();
        });

        function submitConfig() {
            const payload = {
                fullname: field('fullname').value,
                username: field('username').value,
                password: password.value,
                hostname: field('hostname').value
            };

            if (!payload.fullname || !payload.username || !payload.password || !payload.hostname) {
                formError.textContent = T.err_required;
                return;
            }
            // The password is typed blind on a phone keyboard: it must be
            // typed twice before it becomes the only way into the account.
            if (!passwordsMatch()) {
                formError.textContent = T.err_mismatch;
                confirmation.focus();
                return;
            }
            formError.textContent = '';

            fetch('/api/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + companionToken
                },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    field('form-state').style.display = 'none';
                    field('success-state').style.display = 'block';
                } else {
                    formError.textContent = T.err_rejected;
                }
            })
            .catch(err => {
                console.error(err);
                formError.textContent = T.err_connection;
            });
        }
    </script>
</body>
</html>
"""

class CompanionRequestHandler(http.server.SimpleHTTPRequestHandler):
    # StreamRequestHandler.setup() puts this on the connection: a client that
    # stops talking loses its thread after this many seconds.
    timeout = SOCKET_TIMEOUT

    def setup(self):
        """Do the TLS handshake here, on this connection's own thread.

        The listening socket is plain TCP. Wrapping it instead would run the
        handshake inside accept(), where one silent client blocks every
        other one and server.shutdown() with them (#306). No context means
        no connection: the form is never served in clear text (#185).
        """
        context = getattr(self.server, "ssl_context", None)
        if context is None:
            raise ConnectionError("the companion has no TLS context")
        self.request.settimeout(HANDSHAKE_TIMEOUT)
        self.request = context.wrap_socket(self.request, server_side=True)
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            # wrap_socket() took the descriptor from the socket the server
            # holds, so the server's own close does not reach this one.
            try:
                self.request.close()
            except OSError:
                pass

    def _send_body(self, status, content_type, body, extra_headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in extra_headers:
            self.send_header(name, value)
        # The connection closes without a TLS close_notify; the length tells
        # the browser the body is complete.
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress noisy HTTP logging in the installer logs
        pass

    def _token_matches(self, supplied):
        expected = getattr(self.server, "auth_token", None)
        if not expected or not isinstance(supplied, str):
            return False
        return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    def _authorized_path(self, from_header=False):
        """The request path if the session token is valid, else None (403).

        The page is opened from the QR code, so a GET carries the token in
        ?token=. The submission must send it as `Authorization: Bearer`, never
        in the URL, so the token is not repeated in request lines (#227).
        """
        parsed = urlparse(self.path)
        if from_header:
            header = self.headers.get("Authorization") or ""
            scheme, _, supplied = header.partition(" ")
            if scheme.lower() != "bearer":
                supplied = ""
        else:
            supplied = parse_qs(parsed.query).get("token", [""])[0]
        if not self._token_matches(supplied.strip()):
            self.send_error(403, "Forbidden")
            return None
        return parsed.path

    def do_GET(self):
        path = self._authorized_path()
        if path is None:
            return
        if path in ["/", "/index.html"]:
            # The page was fetched with the token in its URL: never cache it,
            # and never send that URL on as a Referer.
            self._send_body(200, "text/html; charset=utf-8",
                            render_companion_html().encode("utf-8"),
                            (("Cache-Control", "no-store"),
                             ("Referrer-Policy", "no-referrer")))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        self._body_taken = False
        try:
            self._handle_post()
        finally:
            self._discard_unread_body()

    def _discard_unread_body(self):
        """Take a refused request's body off the socket before it closes.

        Closing a socket with unread data resets the connection, and the
        reset can reach the phone before the 403 or 409 does.
        """
        if getattr(self, "_body_taken", True):
            return
        self._body_taken = True
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if 0 < length <= MAX_CONFIG_BYTES:
                self.rfile.read(length)
        except (OSError, ValueError):
            pass

    def _handle_post(self):
        path = self._authorized_path(from_header=True)
        if path is None:
            return
        if path == "/api/config":
            # One submission per session. The page polls for the first one
            # and stops the server; a second POST in between must not swap
            # the account details the user just sent.
            if CONFIG_RECEIVED_EVENT.is_set():
                self.send_error(409, "Configuration already received")
                return
            try:
                content_length = int(self.headers['Content-Length'])
                if content_length > MAX_CONFIG_BYTES:
                    self.send_error(413, "Request body too large")
                    return
                self._body_taken = True
                post_data = self.rfile.read(content_length)
                config = sanitize_config(json.loads(post_data.decode('utf-8')))
                if config is None:
                    raise ValueError("payload failed validation")
                
                global GLOBAL_CONFIG
                # Connections run on their own threads now: check and store
                # under one lock, so two posts cannot both be the first.
                with _CONFIG_LOCK:
                    if CONFIG_RECEIVED_EVENT.is_set():
                        self.send_error(409, "Configuration already received")
                        return
                    GLOBAL_CONFIG = config
                    CONFIG_RECEIVED_EVENT.set()
                    # The token is single-use: once the details are in, a copy
                    # of the QR code or the link opens nothing (#227).
                    self.server.auth_token = None

                self._send_body(200, "application/json", b'{"status":"success"}')
            except Exception as e:
                logger.error("Failed to parse POST payload: %s", e)
                self._send_body(400, "application/json", b'{"status":"error"}')
        else:
            self.send_error(404, "Not Found")

def generate_self_signed_cert():
    """Generate a one-day self-signed certificate with openssl.

    Returns (certfile, keyfile) in a fresh private directory, or None. The
    key used to be written to fixed paths in /tmp, where another account on
    the machine could pre-create them. The caller deletes the directory
    (`_remove_cert_dir`) as soon as the pair is loaded.
    """
    certdir = tempfile.mkdtemp(prefix="bootc-companion-")  # mode 0700
    cert = os.path.join(certdir, "cert.pem")
    key = os.path.join(certdir, "key.pem")
    try:
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key,
            "-out", cert,
            "-days", "1", "-nodes",
            "-subj", "/CN=bootc-companion"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cert, key
    except Exception as e:
        logger.warning("Could not generate a self-signed certificate: %s", e)
        shutil.rmtree(certdir, ignore_errors=True)
        return None


def _remove_cert_dir(cert):
    """Delete the directory `generate_self_signed_cert` made for `cert`."""
    certdir = os.path.dirname(cert[1]) if cert else ""
    if os.path.basename(certdir).startswith("bootc-companion-"):
        shutil.rmtree(certdir, ignore_errors=True)


class _CompanionHTTPServer(http.server.ThreadingHTTPServer):
    """One daemon thread per connection, and a cap on how many."""

    daemon_threads = True
    ssl_context = None
    auth_token = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # A failed or timed-out handshake lands here. It is the client's
        # problem, not a traceback for the installer's log.
        logger.debug("Companion connection from %s dropped: %s",
                     client_address[0] if client_address else "?", sys.exc_info()[1])


# stop() hands the listening socket to a thread; start() waits for the ones
# still closing, so the port is free again when it binds.
_PENDING_STOPS = []
_PENDING_STOPS_LOCK = threading.Lock()


def _wait_for_pending_stops(timeout=2.0):
    with _PENDING_STOPS_LOCK:
        pending, _PENDING_STOPS[:] = list(_PENDING_STOPS), []
    for thread in pending:
        thread.join(timeout)


def _shut_down(server):
    try:
        server.shutdown()
        server.server_close()
        logger.info("Stopped Phone Companion server")
    except Exception as e:
        logger.warning("Could not stop the Phone Companion server cleanly: %s", e)


# Why CompanionServer.start() returned False; the page words its message
# from this.
NO_NETWORK = "no-network"
NO_TLS = "no-tls"
BIND_FAILED = "bind-failed"


class CompanionServer:
    NO_NETWORK = NO_NETWORK
    NO_TLS = NO_TLS
    BIND_FAILED = BIND_FAILED

    def __init__(self, port=8443, host=None):
        self.port = port
        # The address the QR code advertises and the only one the server
        # binds. None: found from the default route when the server starts.
        self.host = host
        self.server = None
        self.thread = None
        self.is_https = False
        self.auth_token = None
        self.unavailable_reason = None

    def start(self) -> bool:
        """Serve the companion form over HTTPS. Returns whether it is up.

        There is no plain-HTTP fallback: the form carries the user's
        password, and sending it across the LAN in clear text is worse than
        not offering the phone at all (#185). Without a certificate, or
        without an address a phone can reach, the page tells the user to set
        up on this screen instead; `unavailable_reason` says which.
        """
        global GLOBAL_CONFIG
        GLOBAL_CONFIG = None
        CONFIG_RECEIVED_EVENT.clear()
        self.auth_token = None
        self.is_https = False
        self.unavailable_reason = None
        _wait_for_pending_stops()

        if not self.host:
            self.host = get_local_ip()
        if not self.host:
            logger.warning("Phone Companion disabled: this computer has no network address a phone can reach")
            self.unavailable_reason = self.NO_NETWORK
            return False

        cert = generate_self_signed_cert()
        if cert is None:
            logger.warning("Phone Companion disabled: no TLS certificate, and it will not serve the password over HTTP")
            self.unavailable_reason = self.NO_TLS
            return False

        try:
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(certfile=cert[0], keyfile=cert[1])
            finally:
                # The context holds the key in memory now. Nothing reads the
                # files again, so the private key does not stay on disk for
                # the life of the server, or after a crash (#306).
                _remove_cert_dir(cert)
        except Exception as e:
            logger.error("Phone Companion disabled: the certificate did not load: %s", e)
            self.unavailable_reason = self.NO_TLS
            return False
        self.is_https = True

        try:
            # Only the advertised address: not 0.0.0.0, so the form is not
            # also offered on a VPN, a container bridge or a second network.
            self.server = _CompanionHTTPServer((self.host, self.port), CompanionRequestHandler)
            self.auth_token = secrets.token_urlsafe(32)
            self.server.ssl_context = context
            self.server.auth_token = self.auth_token
            logger.info("Started local HTTPS Phone Companion server on %s:%s", self.host, self.port)

            self.thread = threading.Thread(
                target=self.server.serve_forever,
                kwargs={"poll_interval": _POLL_INTERVAL}, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            logger.error("Failed to start CompanionServer: %s", e)
            if self.server is not None:
                self.server.server_close()
            self.server = None
            self.auth_token = None
            self.unavailable_reason = self.BIND_FAILED
            return False

    def stop(self, wait=False):
        """Stop serving. Returns at once; the socket closes on its own thread.

        The GTK main thread calls this on every page change. shutdown() waits
        for the serve loop, so it runs on a daemon thread and the window
        never waits for it (#306). The token dies here, before that thread
        runs: a request still in flight gets 403. `wait=True` is for tests
        and for callers that are not the main thread. Returns the thread, or
        None when the server was not running.
        """
        server, self.server = self.server, None
        self.auth_token = None
        self.thread = None
        if server is None:
            return None
        server.auth_token = None
        stopper = threading.Thread(target=_shut_down, args=(server,), daemon=True)
        with _PENDING_STOPS_LOCK:
            _PENDING_STOPS.append(stopper)
        stopper.start()
        if wait:
            stopper.join()
        return stopper

    def get_config(self):
        return GLOBAL_CONFIG
