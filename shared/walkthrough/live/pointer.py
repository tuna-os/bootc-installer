"""A pointer for a headless wlroots compositor.

The headless backend has no pointer device, so a seat has no pointer and
`swaymsg seat cursor press` reaches no window. This speaks just enough of the
Wayland wire protocol to create one zwlr_virtual_pointer_v1 and move it.
"""

import os
import socket
import struct
import time

BTN_LEFT = 0x110


class Pointer:
    def __init__(self, runtime_dir, display, width, height):
        self.width, self.height = width, height
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(os.path.join(runtime_dir, display))
        self.sock.settimeout(5)
        self.buf = b""
        self.next_id = 2
        registry, done = self._id(), self._id()
        self._send(1, 1, struct.pack("<I", registry))    # wl_display.get_registry
        self._send(1, 0, struct.pack("<I", done))        # wl_display.sync
        manager = None
        while True:
            obj, opcode, body = self._event()
            if obj == registry and opcode == 0:
                name, length = struct.unpack("<II", body[:8])
                interface = body[8:8 + length - 1].decode()
                if interface == "zwlr_virtual_pointer_manager_v1":
                    manager = name
            elif obj == done:
                break
            elif obj == 1 and opcode == 0:
                raise RuntimeError("Wayland protocol error")
        if manager is None:
            raise RuntimeError("the compositor has no virtual pointer protocol")
        mgr, self.ptr = self._id(), self._id()
        text = b"zwlr_virtual_pointer_manager_v1\0"
        text += b"\0" * (-len(text) % 4)
        self._send(registry, 0, struct.pack("<II", manager, 32) + text
                   + struct.pack("<II", 1, mgr))
        self._send(mgr, 0, struct.pack("<II", 0, self.ptr))  # no seat: the default one

    def _id(self):
        self.next_id += 1
        return self.next_id - 1

    def _send(self, obj, opcode, body):
        self.sock.sendall(struct.pack("<II", obj, (len(body) + 8) << 16 | opcode) + body)

    def _event(self):
        while len(self.buf) < 8 or len(self.buf) < struct.unpack("<I", self.buf[4:8])[0] >> 16:
            data = self.sock.recv(65536)
            if not data:
                raise RuntimeError("the compositor closed the connection")
            self.buf += data
        obj, word = struct.unpack("<II", self.buf[:8])
        size = word >> 16
        body, self.buf = self.buf[8:size], self.buf[size:]
        return obj, word & 0xffff, body

    @staticmethod
    def _now():
        return int(time.monotonic() * 1000) & 0xffffffff

    def _frame(self):
        self._send(self.ptr, 4, b"")

    def move(self, x, y):
        self._send(self.ptr, 1, struct.pack("<IIIII", self._now(), int(x), int(y),
                                            self.width, self.height))
        self._frame()

    def button(self, pressed):
        self._send(self.ptr, 2, struct.pack("<III", self._now(), BTN_LEFT, int(pressed)))
        self._frame()

    def scroll(self, steps):
        """A wheel: positive goes down. Each step is one detent."""
        for _ in range(abs(steps)):
            value = 15 * (1 if steps > 0 else -1)
            self._send(self.ptr, 5, struct.pack("<I", 0))                     # source wheel
            self._send(self.ptr, 7, struct.pack("<IIii", self._now(), 0, value * 256,
                                                1 if steps > 0 else -1))      # axis_discrete
            self._frame()
            time.sleep(0.03)
