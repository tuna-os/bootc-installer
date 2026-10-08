# sha512crypt.py
#
# SHA-512 crypt(3), the "$6$" password hash, in plain Python.
#
# The installer hashes the user's password before it reaches fisherman
# (#79), and the flatpak's Python (GNOME 50 runtime, 3.13+) no longer ships
# the `crypt` module. Shelling out to `openssl passwd` would depend on a CLI
# the runtime need not carry. This is Ulrich Drepper's published algorithm
# (https://www.akkadia.org/drepper/SHA-crypt.txt), checked in the unit tests
# against the spec's own vectors and against crypt/openssl where present.

import hashlib
import secrets

_ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_ROUNDS_DEFAULT = 5000
_ROUNDS_MIN = 1000
_ROUNDS_MAX = 999_999_999

# Byte order of the final digest in the encoded output, from the spec.
_PERMUTATION = (
    (0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4),
    (47, 5, 26), (6, 27, 48), (28, 49, 7), (50, 8, 29), (9, 30, 51),
    (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13), (56, 14, 35),
    (15, 36, 57), (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19),
    (62, 20, 41),
)


def _b64_from_24bit(b2: int, b1: int, b0: int, n: int) -> str:
    w = (b2 << 16) | (b1 << 8) | b0
    out = []
    for _ in range(n):
        out.append(_ITOA64[w & 0x3F])
        w >>= 6
    return "".join(out)


def _repeat_to(block: bytes, length: int) -> bytes:
    return (block * (length // len(block) + 1))[:length]


def sha512_crypt(password: str, salt: str | None = None, rounds: int | None = None) -> str:
    """Hash `password` as a "$6$" crypt string.

    `salt` (at most 16 characters are used) is random when omitted. `rounds`
    is clamped to the spec's range and written into the result only when it
    is not the default 5000, as glibc does.
    """
    p = password.encode("utf-8")
    if salt is None:
        salt = "".join(secrets.choice(_ITOA64) for _ in range(16))
    s = salt.encode("utf-8")[:16]

    custom_rounds = rounds is not None
    rounds = _ROUNDS_DEFAULT if rounds is None else min(max(rounds, _ROUNDS_MIN), _ROUNDS_MAX)

    b = hashlib.sha512(p + s + p).digest()

    a = hashlib.sha512(p + s)
    a.update(_repeat_to(b, len(p)))
    n = len(p)
    while n:
        a.update(b if n & 1 else p)
        n >>= 1
    a = a.digest()

    p_bytes = _repeat_to(hashlib.sha512(p * len(p)).digest(), len(p))
    s_bytes = _repeat_to(hashlib.sha512(s * (16 + a[0])).digest(), len(s))

    c = a
    for i in range(rounds):
        h = hashlib.sha512()
        h.update(p_bytes if i % 2 else c)
        if i % 3:
            h.update(s_bytes)
        if i % 7:
            h.update(p_bytes)
        h.update(c if i % 2 else p_bytes)
        c = h.digest()

    encoded = "".join(_b64_from_24bit(c[x], c[y], c[z], 4) for x, y, z in _PERMUTATION)
    encoded += _b64_from_24bit(0, 0, c[63], 2)

    prefix = f"$6$rounds={rounds}$" if custom_rounds else "$6$"
    return f"{prefix}{s.decode('utf-8')}${encoded}"
