"""The Varlink client examples and the size helper in shared/client/.

The Python client is stdlib only. The tests run it against a scripted peer
on a UNIX socket. The peer is a test double for the wire format; it is not
the mock daemon of tuna-os/fisherman. The Go, C++ and Rust examples read the
same `fixtures/sizes.json`, and their own tests run them (see
shared/client/README.md).
"""

import json
import os
import pathlib
import socket
import sys
import tempfile
import threading

import pytest

CLIENT = pathlib.Path(__file__).resolve().parents[2] / "shared" / "client"
sys.path.insert(0, str(CLIENT / "python"))

import sizes  # noqa: E402
import varlink_client  # noqa: E402
from varlink_client import Connection, ProtocolError, VarlinkError  # noqa: E402

CASES = json.loads((CLIENT / "fixtures" / "sizes.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_size_fixture(case):
    assert sizes.normalize_size_text(case["input"]) == case["normalized"]
    assert sizes.parse_size(case["input"]) == case["bytes"]


def test_fixture_inputs_contain_the_characters_they_name():
    by_name = {c["name"]: c["input"] for c in CASES}
    assert "\u00a0" in by_name["nbsp"]
    assert "\u202f" in by_name["narrow-nbsp"]


def test_normalised_text_has_only_plain_spaces():
    for case in CASES:
        out = sizes.normalize_size_text(case["input"])
        assert all(ch == " " or not ch.isspace() for ch in out)


class Peer:
    """Serves one connection. `script` gets the decoded request and the raw
    socket, and writes the reply messages itself."""

    def __init__(self, script):
        self.dir = tempfile.mkdtemp(prefix="vl")
        self.path = os.path.join(self.dir, "s")
        self.requests = []
        self._script = script
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.path)
        self._server.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            self._loop()
        except OSError:
            pass  # the test closed the socket

    def _loop(self):
        conn, _ = self._server.accept()
        with conn:
            data = b""
            while True:
                while b"\0" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    data += chunk
                raw, _, data = data.partition(b"\0")
                request = json.loads(raw)
                self.requests.append(request)
                self._script(request, conn)

    def close(self):
        self._server.close()
        try:
            os.unlink(self.path)
            os.rmdir(self.dir)
        except OSError:
            pass


def send(conn, *messages, split=None):
    blob = b"".join(json.dumps(m).encode() + b"\0" for m in messages)
    if split:
        conn.sendall(blob[:split])
        conn.sendall(blob[split:])
    else:
        conn.sendall(blob)


@pytest.fixture
def peer():
    made = []

    def make(script):
        p = Peer(script)
        made.append(p)
        return p

    yield make
    for p in made:
        p.close()


def test_call_frames_the_request_with_a_nul_byte(peer):
    p = peer(lambda req, conn: send(conn, {"parameters": {"vendor": "test"}}))
    with Connection(p.path, timeout=5) as c:
        assert c.get_info() == {"vendor": "test"}
    assert p.requests == [{"method": "org.varlink.service.GetInfo", "parameters": {}}]


def test_call_more_yields_each_reply_and_the_empty_end(peer):
    def script(req, conn):
        send(conn,
             {"parameters": {"phase": "install_partitions", "progress": 10}, "continues": True},
             {"parameters": {"phase": "install_partitions", "progress": 100}, "continues": True},
             {"parameters": {}})

    p = peer(script)
    with Connection(p.path, timeout=5) as c:
        got = list(c.call_more("io.systemd.SysInstall.Run", {"node": "/dev/vda"}))
    assert [r.get("progress") for r in got] == [10, 100, None]
    assert p.requests[0]["more"] is True


def test_a_reply_split_across_reads_is_reassembled(peer):
    p = peer(lambda req, conn: send(conn, {"parameters": {"node": "/dev/vda"}}, split=7))
    with Connection(p.path, timeout=5) as c:
        assert c.call("io.systemd.SysInstall.ListCandidateDevices") == {"node": "/dev/vda"}


def test_two_replies_in_one_read_are_both_seen(peer):
    p = peer(lambda req, conn: send(
        conn, {"parameters": {"n": 1}, "continues": True}, {"parameters": {"n": 2}}))
    with Connection(p.path, timeout=5) as c:
        assert [r["n"] for r in c.call_more("x.Y")] == [1, 2]


def test_an_error_reply_raises_with_its_name_and_parameters(peer):
    p = peer(lambda req, conn: send(conn, {
        "error": "io.systemd.SysInstall.DiskTooSmall",
        "parameters": {"minimalSizeBytes": 10, "currentSizeBytes": 5}}))
    with Connection(p.path, timeout=5) as c:
        with pytest.raises(VarlinkError) as caught:
            c.call("io.systemd.SysInstall.Run", {"node": "/dev/vda"})
    assert caught.value.error == "io.systemd.SysInstall.DiskTooSmall"
    assert caught.value.parameters["minimalSizeBytes"] == 10


def test_an_error_in_a_stream_ends_it(peer):
    p = peer(lambda req, conn: send(
        conn, {"parameters": {"progress": 5}, "continues": True},
        {"error": "io.tunaos.Fisherman.DeviceLost"}))
    with Connection(p.path, timeout=5) as c:
        stream = c.call_more("io.tunaos.Fisherman.Install")
        assert next(stream) == {"progress": 5}
        with pytest.raises(VarlinkError) as caught:
            next(stream)
    assert caught.value.error == "io.tunaos.Fisherman.DeviceLost"


def test_an_error_text_does_not_carry_the_parameters(peer):
    p = peer(lambda req, conn: send(conn, {
        "error": "x.Failed", "parameters": {"passphrase": "hunter2"}}))
    with Connection(p.path, timeout=5) as c:
        with pytest.raises(VarlinkError) as caught:
            c.call("x.Run")
    assert "hunter2" not in str(caught.value)
    assert "hunter2" not in repr(caught.value)


def test_oneway_sends_the_flag_and_waits_for_nothing(peer):
    p = peer(lambda req, conn: None)
    with Connection(p.path, timeout=5) as c:
        c.call_oneway("io.tunaos.Fisherman.Cancel")
    for _ in range(100):
        if p.requests:
            break
        threading.Event().wait(0.02)
    assert p.requests[0]["oneway"] is True


def test_a_closed_connection_is_a_protocol_error(peer):
    p = peer(lambda req, conn: conn.close())
    with Connection(p.path, timeout=5) as c:
        with pytest.raises(ProtocolError):
            c.call("x.Y")


def test_a_message_that_is_not_json_is_a_protocol_error(peer):
    p = peer(lambda req, conn: conn.sendall(b"not json\0"))
    with Connection(p.path, timeout=5) as c:
        with pytest.raises(ProtocolError):
            c.call("x.Y")


def test_the_module_is_stdlib_only():
    source = (CLIENT / "python" / "varlink_client.py").read_text(encoding="utf-8")
    imports = {line.split()[1].split(".")[0] for line in source.splitlines()
               if line.startswith(("import ", "from "))}
    assert imports <= {"json", "socket"}
    assert varlink_client.NUL == b"\0"
