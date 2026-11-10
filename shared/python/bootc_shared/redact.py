"""The recovery key does not stay in a log.

fisherman prints the TPM recovery key in its output (the `recovery_key`
event). The key belongs on the recovery-key page and nowhere else: a log
file, a log dialog, the clipboard and a log that a user attaches to a bug
report must not carry it (#316, #337). shared/progress/README.md
("Recovery key in a log") has the rule, and
shared/progress/recovery-key-cases.json the cases that each frontend's
redaction must pass, byte for byte.
"""

import json
import logging
import os
import re

logger = logging.getLogger("Installer::Redact")

# What replaces a recovery key wherever a log is kept or leaves the app.
REDACTED = "[redacted]"

# fisherman's recovery_key event: {"type":"recovery_key","key":"..."}.
_RE_KEY_EVENT = re.compile(r'("key"\s*:\s*")(?:[^"\\]|\\.)*(")')
# The line the shared parser renders for that event (render_event).
_RE_KEY_LINE = re.compile(r"(Recovery key:\s*)\S.*")


def redact_recovery_key(text: str, known_key: str = "") -> str:
    """`text` with every recovery key replaced by REDACTED.

    Three forms are removed: the value of a `recovery_key` event, the
    "Recovery key: ..." line the parser renders for it, and `known_key`
    itself wherever fisherman's stderr repeats it.
    """
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        if '"recovery_key"' in line:
            line = _RE_KEY_EVENT.sub(r"\g<1>" + REDACTED + r"\g<2>", line)
        line = _RE_KEY_LINE.sub(r"\g<1>" + REDACTED, line)
        out.append(line)
    text = "\n".join(out)
    known_key = (known_key or "").strip()
    if known_key:
        text = text.replace(known_key, REDACTED)
    return text


def read_log_redacted(path: str, known_key: str = ""):
    """The log file's text without the recovery key, or None when it cannot
    be read. The one way a log leaves the process (clipboard, dialog)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return redact_recovery_key(fh.read(), known_key)
    except OSError:
        return None


def scrub_log_file(path: str, known_key: str = "") -> bool:
    """Rewrite the log at `path` without the recovery key. True when the
    file no longer holds one (also when there is no file).

    The file is rewritten in place, so its mode stays. When the rewrite
    fails the file is removed: a missing log is better than a key on disk.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except FileNotFoundError:
        return True
    except OSError as e:
        logger.error("Could not read %s to scrub it: %s", path, e)
        text = None
    if text is not None:
        clean = redact_recovery_key(text, known_key)
        if clean == text:
            return True
        try:
            fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(clean)
            logger.info("Removed the recovery key from %s", path)
            return True
        except OSError as e:
            logger.error("Could not rewrite %s: %s", path, e)
    try:
        os.unlink(path)
        return True
    except OSError as e:
        logger.error("Could not remove %s: %s", path, e)
        return False


class LogRedactor:
    """Redaction for a log that is written one line at a time.

    A writer that sees fisherman's output as a stream cannot wait for the
    whole text. It sends each line through line() before the line reaches
    the file. The redactor remembers the key of the `recovery_key` event,
    so that a later line that repeats the key loses it too.
    """

    def __init__(self):
        self.known_key = ""

    def line(self, text: str) -> str:
        if text and '"recovery_key"' in text:
            try:
                event = json.loads(text)
            except ValueError:
                event = None
            if isinstance(event, dict) and event.get("type") == "recovery_key":
                key = event.get("key")
                if isinstance(key, str) and key.strip() and key != REDACTED:
                    self.known_key = key.strip()
        return redact_recovery_key(text, self.known_key)
