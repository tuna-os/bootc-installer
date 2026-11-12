#!/usr/bin/env python3
"""What the end-to-end and walkthrough jobs may publish (#270).

A recipe holds the LUKS passphrase and the account password. In the E2E
jobs they are synthetic test values, but an artifact is downloadable by
anyone who can read the run, so no job uploads a raw recipe or a raw log.
Each job writes its evidence to a private directory and copies to a
publication staging directory only what this module allows:

  * a recipe summary: an allowlist of recipe keys, the secret fields
    replaced by a fixed marker (never a hash of the value), the names of
    the keys left out;
  * a redacted recipe: the frontend's exact bytes with each secret value
    replaced by the marker of its field. The VM install job restores the
    values from test-credentials.json, the values that the drivers type,
    so no secret passes between jobs;
  * logs, with every secret value replaced by the marker and the size
    capped.

    publish.py summary <recipe.json> [--frontend NAME]
        print the summary of a recipe
    publish.py stage --recipe <recipe.json> --frontend NAME --out DIR [LOG ...]
        write the summary and the redacted logs to DIR (an allowlist of
        names); a file that is not on the allowlist is not copied
    publish.py redact-stream --recipe <recipe.json>
        copy stdin to stdout with the recipe's secret values replaced
    publish.py audit DIR [DIR ...]
        fail when a published directory has a file type that is not on the
        allowlist, a recipe secret with a value, or a known test credential

Only this module decides what is a secret field. A new secret field in the
recipe schema must go in SECRET_FIELDS: tests/unit/test_e2e_publication.py
fails on a schema property whose name looks like a secret and is not here.
"""
import argparse
import fnmatch
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS = os.path.join(HERE, "test-credentials.json")

# (block, key): the recipe fields that hold a secret.
SECRET_FIELDS = (("encryption", "passphrase"), ("user", "password"))
MARKER = "<redacted>"

# Top-level recipe keys that the summary copies as they are. Every other
# key is left out by name: `user` and `encryption` are summarised below,
# and `slurp`, `override` and anything new are not published.
SUMMARY_KEYS = frozenset({
    "disk", "filesystem", "btrfsSubvolumes", "image", "targetImgref",
    "sourceReuse", "bootloader", "composeFsBackend", "flatpaks",
    "additionalImageStores", "distroID", "selinuxDisabled", "hostname",
    "unifiedStorage", "genericImage", "zfsPoolName", "imageType",
    "flatpakVarPath", "customMounts", "varDisk", "slurpWallpapers",
    "targetMount", "luksMapperName", "brewTap", "copyNetworkProfiles",
    "copyBluetoothPairings", "extras", "experimental", "setBootNext",
    "locale", "keyboard", "timezone",
})
# Keys of a nested block that the summary copies. The secret key of the
# block is in the summary as MARKER when the recipe has it.
SUMMARY_BLOCK_KEYS = {"encryption": frozenset({"type"}),
                      "user": frozenset({"username", "groups"})}

# File names that a staging directory may hold.
STAGE_ALLOWLIST = (
    "e2e-recipe-*.summary.json",   # the summary
    "e2e-recipe-*.redacted.json",  # the redacted bytes for the VM job
    "install.log", "boot.log",     # vm-install.sh
    "serial-*.log", "journal-*.log", "qemu-stdout-*.log",  # boot-verify.sh
    "bootc-status-*.log", "bootctl-status-*.log", "efibootmgr-*.log",
    "ssh-probe-*.log", "qemu-info-status-*.log",
)
# File types that a published walkthrough directory may hold.
AUDIT_SUFFIXES = (".png", ".gif", ".json", ".md")
# The size of one published log. The start of a log has the first failure
# and the end has the last state, so a long log keeps both.
LOG_CAP = 4 * 1024 * 1024


def field_marker(block, key):
    """The marker that takes the place of one secret in a redacted recipe."""
    return f"{MARKER[:-1]}:{block}.{key}>"


def secret_values(recipe):
    """{"block.key": value} for each secret that the recipe holds."""
    found = {}
    for block, key in SECRET_FIELDS:
        section = recipe.get(block) if isinstance(recipe, dict) else None
        if isinstance(section, dict) and isinstance(section.get(key), str) and section[key]:
            found[f"{block}.{key}"] = section[key]
    return found


def redact_text(text, secrets):
    """text with every secret value replaced by MARKER. The longest value
    goes first, so a value that holds another one is replaced whole."""
    for value in sorted(set(secrets), key=len, reverse=True):
        if value:
            text = text.replace(value, MARKER)
    return text


def summary(recipe, frontend=None):
    """The allowlisted, redacted view of a recipe."""
    out = {}
    withheld = []
    redacted = []
    for key in sorted(recipe):
        value = recipe[key]
        if key in SUMMARY_BLOCK_KEYS and isinstance(value, dict):
            block = {k: value[k] for k in sorted(value) if k in SUMMARY_BLOCK_KEYS[key]}
            for name in sorted(value):
                if (key, name) in SECRET_FIELDS:
                    block[name] = MARKER
                    redacted.append(f"{key}.{name}")
                elif name not in SUMMARY_BLOCK_KEYS[key]:
                    withheld.append(f"{key}.{name}")
            out[key] = block
        elif key in SUMMARY_KEYS:
            out[key] = value
        else:
            withheld.append(key)
    result = {"kind": "e2e-recipe-summary", "version": 1}
    if frontend:
        result["frontend"] = frontend
    result.update({"recipe": out, "redacted": redacted, "withheld": withheld})
    return result


def redact_bytes(raw):
    """The recipe bytes with each secret's JSON string replaced by the
    marker of its field. Raises ValueError, with no secret in the message,
    when that is not safe: the value is not written as json.dumps writes
    it, it is in the bytes more than once, or it is somewhere else too."""
    recipe = json.loads(raw)
    secrets = secret_values(recipe)
    out = raw
    for name, value in secrets.items():
        token = json.dumps(value).encode()
        count = out.count(token)
        if count != 1:
            raise ValueError(f"{name}: its JSON string is in the recipe {count} times, "
                             "so it cannot be redacted by position")
        block, key = name.split(".")
        out = out.replace(token, json.dumps(field_marker(block, key)).encode())
    for name, value in secrets.items():
        if value.encode() in out:
            raise ValueError(f"{name}: its value is also in another field of the recipe")
    return out


def load_credentials(path=None):
    """The test credentials of the E2E drivers: {frontend: {field: value}}."""
    path = path or os.environ.get("TUNA_E2E_CREDENTIALS") or CREDENTIALS
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    return data["frontends"]


def restore_bytes(redacted, frontend, credentials):
    """The inverse of redact_bytes: each field marker replaced by the test
    value of that frontend. Raises ValueError (no value in the message)
    when a marker has no test value."""
    known = credentials.get(frontend, {})
    out = redacted
    for block, key in SECRET_FIELDS:
        token = json.dumps(field_marker(block, key)).encode()
        if token not in out:
            continue
        name = f"{block}.{key}"
        if name not in known:
            raise ValueError(f"{name}: test-credentials.json has no value for {frontend!r}")
        out = out.replace(token, json.dumps(known[name]).encode())
    return out


def _matches(name, patterns):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _cap(text):
    if len(text) <= LOG_CAP:
        return text
    half = LOG_CAP // 2
    cut = len(text) - 2 * half
    return f"{text[:half]}\n[... {cut} characters cut by shared/e2e/publish.py ...]\n{text[-half:]}"


def write_staged(out_dir, name, text):
    """Write one file to the staging directory, if the allowlist has it."""
    if os.sep in name or not _matches(name, STAGE_ALLOWLIST):
        raise ValueError(f"{name}: not on the publication allowlist")
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as stream:
        stream.write(text)


def stage(recipe_path, frontend, out_dir, logs=(), extra_secrets=()):
    """Write the summary and the redacted logs to out_dir. Returns the
    names written and the names refused."""
    os.makedirs(out_dir, exist_ok=True)
    secrets = list(extra_secrets)
    written, refused = [], []
    recipe = None
    if recipe_path and os.path.exists(recipe_path):
        with open(recipe_path, "rb") as stream:
            raw = stream.read()
        try:
            recipe = json.loads(raw)
        except ValueError:
            recipe = None
        if isinstance(recipe, dict):
            secrets += list(secret_values(recipe).values())
            name = f"e2e-recipe-{frontend}.summary.json"
            write_staged(out_dir, name, json.dumps(summary(recipe, frontend), indent=2) + "\n")
            written.append(name)
    for log in logs:
        name = os.path.basename(log)
        if not os.path.isfile(log):
            continue
        if not _matches(name, STAGE_ALLOWLIST) or name.endswith(".json"):
            refused.append(name)
            continue
        with open(log, encoding="utf-8", errors="replace") as stream:
            text = stream.read()
        write_staged(out_dir, name, _cap(redact_text(text, secrets)))
        written.append(name)
    return written, refused


def audit_failures(directories, credentials=None):
    """Problems in published directories: a file type that is not on the
    allowlist, a JSON object with a secret field that holds a value, or a
    test credential anywhere in a text file."""
    if credentials is None:
        try:
            credentials = load_credentials()
        except (OSError, ValueError, KeyError):
            credentials = {}
    known = sorted({v for fields in credentials.values() for v in fields.values() if v},
                   key=len, reverse=True)
    secret_keys = {key for _block, key in SECRET_FIELDS}
    failures = []
    for top in directories:
        for root, _dirs, files in os.walk(top):
            for name in sorted(files):
                path = os.path.join(root, name)
                rel = os.path.relpath(path, top)
                if not name.lower().endswith(AUDIT_SUFFIXES):
                    failures.append(f"{rel}: the file type is not on the publication allowlist")
                    continue
                if name.lower().endswith((".png", ".gif")):
                    continue
                with open(path, encoding="utf-8", errors="replace") as stream:
                    text = stream.read()
                if any(value in text for value in known):
                    failures.append(f"{rel}: holds an E2E test credential")
                if name.lower().endswith(".json"):
                    for key, value in _json_pairs(text):
                        if key in secret_keys and isinstance(value, str) and value \
                                and not value.startswith(MARKER[:-1]):
                            failures.append(f"{rel}: {key!r} holds a value, not {MARKER}")
    return failures


def _json_pairs(text):
    try:
        data = json.loads(text)
    except ValueError:
        return []
    pairs = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                pairs.append((key, value))
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return pairs


def _read_recipe(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("summary")
    p.add_argument("recipe")
    p.add_argument("--frontend")
    p = sub.add_parser("stage")
    p.add_argument("--recipe")
    p.add_argument("--frontend", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("logs", nargs="*")
    p = sub.add_parser("redact-stream")
    p.add_argument("--recipe", required=True)
    p = sub.add_parser("audit")
    p.add_argument("dirs", nargs="+")
    args = parser.parse_args(argv)

    if args.cmd == "summary":
        print(json.dumps(summary(_read_recipe(args.recipe), args.frontend), indent=2))
        return 0
    if args.cmd == "stage":
        written, refused = stage(args.recipe, args.frontend, args.out, args.logs)
        for name in written:
            print(f"published: {name}")
        for name in refused:
            print(f"not published (not on the allowlist): {name}")
        return 0
    if args.cmd == "redact-stream":
        secrets = list(secret_values(_read_recipe(args.recipe)).values())
        for line in sys.stdin:
            sys.stdout.write(redact_text(line, secrets))
            sys.stdout.flush()
        return 0
    failures = audit_failures(args.dirs)
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if not failures:
        print(f"publication audit: ok ({', '.join(args.dirs)})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
