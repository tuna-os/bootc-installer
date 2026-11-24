"""A thin Varlink client: JSON over a UNIX socket, stdlib only.

The wire format is small:

- A message is one JSON object followed by a NUL byte (0x00).
- A call is {"method": "<interface>.<Method>", "parameters": {...}}.
  Add "more": true to ask for a stream of replies, and "oneway": true to
  get no reply.
- A reply is {"parameters": {...}}. In a stream, every reply but the last
  has "continues": true. The last has none, and its parameters may be empty.
- An error is {"error": "<interface>.<Name>", "parameters": {...}}. It ends
  the call.

One connection carries one call at a time. Open a second connection for a
second call, for example to cancel a running install.

Passphrases and recovery keys pass through `parameters`. This module never
logs them. Do not log a request or a reply in code that uses it.
"""

import json
import socket

NUL = b"\0"
# The interface that every Varlink service has.
SERVICE_INTERFACE = "org.varlink.service"


class VarlinkError(Exception):
    """The service answered with an error reply."""

    def __init__(self, error, parameters=None):
        super().__init__(error)
        self.error = error
        self.parameters = parameters or {}

    def __str__(self):
        # Only the error name. The parameters can hold a secret.
        return self.error


class ProtocolError(Exception):
    """The peer sent something that is not a Varlink message."""


class Connection:
    """One connection to a Varlink service socket."""

    def __init__(self, path, timeout=None):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect(path)
        self._buffer = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        self._sock.close()

    # -- framing ---------------------------------------------------------

    def _send(self, message):
        self._sock.sendall(json.dumps(message, separators=(",", ":")).encode("utf-8") + NUL)

    def _receive(self):
        """Read one NUL-terminated message and return it as a dict."""
        while True:
            end = self._buffer.find(NUL)
            if end >= 0:
                raw = bytes(self._buffer[:end])
                del self._buffer[:end + 1]
                break
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ProtocolError("the service closed the connection")
            self._buffer.extend(chunk)
        try:
            message = json.loads(raw)
        except ValueError as error:
            raise ProtocolError("a message is not JSON") from error
        if not isinstance(message, dict):
            raise ProtocolError("a message is not an object")
        return message

    @staticmethod
    def _unwrap(message):
        """Return (parameters, continues) or raise VarlinkError."""
        if "error" in message:
            raise VarlinkError(message["error"], message.get("parameters"))
        return message.get("parameters") or {}, bool(message.get("continues"))

    # -- calls -----------------------------------------------------------

    def call(self, method, parameters=None):
        """Call a method with one reply. Return the reply parameters."""
        self._send({"method": method, "parameters": parameters or {}})
        reply, _continues = self._unwrap(self._receive())
        return reply

    def call_more(self, method, parameters=None):
        """Call a streaming method. Yield the parameters of each reply.

        The generator ends after the last reply. That reply can have empty
        parameters (the end of a run): the generator yields it as {}, so a
        caller sees the end as well as the progress. Closing the generator
        early leaves unread replies on the connection. Close the connection
        in that case.
        """
        self._send({"method": method, "parameters": parameters or {}, "more": True})
        while True:
            reply, continues = self._unwrap(self._receive())
            yield reply
            if not continues:
                return

    def call_oneway(self, method, parameters=None):
        """Call a method and do not wait for a reply."""
        self._send({"method": method, "parameters": parameters or {}, "oneway": True})

    def get_info(self):
        """org.varlink.service.GetInfo: vendor, product, version, interfaces."""
        return self.call(SERVICE_INTERFACE + ".GetInfo")
