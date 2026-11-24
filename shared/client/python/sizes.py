"""Size text from a toolkit, made comparable (projectbluefin/utah#1437).

GLib's g_format_size puts a no-break space (U+00A0) between the number and
the unit. Some locales use the narrow no-break space (U+202F), and Qt and
ICU can emit the thin space (U+2009). A test that compares "500.1 GB" with
the text of an AT-SPI node then fails on an invisible character.

`normalize_size_text` makes one plain space of each run of spaces and drops
invisible marks. `parse_size` turns "1.0 TB" into bytes. Both are stdlib
only. The other languages in shared/client implement the same cases from
`fixtures/sizes.json`.
"""

import re

# Characters that look like a space and are not U+0020.
_SPACES = (
    "\u00a0"  # no-break space (GLib)
    "\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007"  # figure space
    "\u2008\u2009\u200a"  # punctuation space, thin, hair
    "\u202f"  # narrow no-break space
    "\u205f\u3000"
)
# Characters that have no width and no place in a comparison.
_INVISIBLE = "\u200b\u200c\u200d\u200e\u200f\u2060\u2066\u2067\u2068\u2069\ufeff\u00ad"

_TABLE = {ord(c): " " for c in _SPACES}
_TABLE.update({ord(c): None for c in _INVISIBLE})

_UNITS = {
    "b": 1, "byte": 1, "bytes": 1,
    "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12, "pb": 10**15,
    "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40, "pib": 2**50,
}

_SIZE = re.compile(r"^(?P<num>\d[\d.,]*)\s?(?P<unit>[A-Za-z]+)$")


def normalize_size_text(text):
    """Return `text` with each run of space-like characters made one space.

    The text is trimmed, and invisible marks are removed. The function does
    not change digits, letters or punctuation.
    """
    plain = text.translate(_TABLE)
    return " ".join(plain.split())


def _number(raw):
    """Read "1.5", "1,5" and "1,500" as a float. None when it is neither."""
    if "." in raw and "," in raw:
        # "1,500.5": the comma groups, the dot is the decimal mark.
        raw = raw.replace(",", "")
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        # A comma followed by exactly three digits groups ("1,500").
        # Any other comma is a decimal mark ("1,5").
        raw = (head + tail).replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    try:
        return float(raw)
    except ValueError:
        return None


def parse_size(text):
    """Return the size in bytes, or None when `text` is not one size.

    SI units (kB, MB, GB, TB) are powers of 1000, as g_format_size writes
    them. IEC units (KiB, GiB) are powers of 1024.
    """
    match = _SIZE.match(normalize_size_text(text))
    if not match:
        return None
    unit = _UNITS.get(match.group("unit").lower())
    value = _number(match.group("num"))
    if unit is None or value is None:
        return None
    return int(round(value * unit))
