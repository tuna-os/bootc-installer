"""What the E2E and walkthrough jobs publish (#270).

Sentinel credentials go into the recipe, the logs and the inputs (the
credentials file and the backend's answer). None of them may reach the
publication staging directory or the console output, in any form: as
they are, as a hash, or as base64. Only allowlisted, redacted evidence is
staged, and the VM job can still restore the frontend's exact bytes.
"""

import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
E2E = os.path.join(REPO, "shared", "e2e")
CHECK = os.path.join(E2E, "check-recipe.py")
PUBLISH = os.path.join(E2E, "publish.py")

_spec = importlib.util.spec_from_file_location("e2e_publish", PUBLISH)
publish = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish)

PASSPHRASE = "SENTINEL-luks-7f3a9c"
PASSWORD = "SENTINEL-pw-41be02"
SENTINELS = (PASSPHRASE, PASSWORD)
RECIPE = (
    '{\n  "disk": "/dev/loop0",\n  "image": "registry.example/os/atlas:stable",\n'
    '  "hostname": "e2e-host",\n  "filesystem": "xfs",\n'
    f'  "encryption": {{"type": "luks-passphrase", "passphrase": "{PASSPHRASE}"}},\n'
    f'  "user": {{"username": "e2euser", "fullname": "E2E User", "password": "{PASSWORD}", '
    '"groups": ["wheel"]},\n  "slurp": {"sourcePartition": "/dev/sdz9"}\n}\n'
).encode()


def _forms(value):
    """Every form of a sentinel that would give it away."""
    raw = value.encode()
    return (value, hashlib.sha256(raw).hexdigest(), hashlib.md5(raw).hexdigest(),
            hashlib.sha1(raw).hexdigest(), base64.b64encode(raw).decode())


def _env(tmp, credentials):
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    env["TUNA_E2E_DIR"] = os.path.join(tmp, "e2e")
    env["TUNA_E2E_REAL"] = os.path.join(tmp, "fisherman.real")
    env["TUNA_E2E_CREDENTIALS"] = credentials
    return env


def _write(path, data, mode=0o644):
    with open(path, "wb" if isinstance(data, bytes) else "w") as stream:
        stream.write(data)
    os.chmod(path, mode)


def _setup(tmp, passphrase=PASSPHRASE):
    os.makedirs(os.path.join(tmp, "e2e"))
    _write(os.path.join(tmp, "e2e", "recipe.json"), RECIPE)
    # A backend that echoes the passphrase in its answer: the console and
    # the staging directory must still not show it.
    _write(os.path.join(tmp, "fisherman.real"),
           "#!/bin/sh\ncat >/dev/null\n"
           "printf '%s\\n' '{\"valid\": false, \"errors\": [{\"field\": "
           f"\"encryption.passphrase\", \"code\": \"x\", \"message\": \"bad {PASSPHRASE}\"}}]}}'\n"
           "exit 1\n", 0o755)
    credentials = os.path.join(tmp, "credentials.json")
    _write(credentials, json.dumps({"frontends": {"kde": {
        "encryption.passphrase": passphrase, "user.password": PASSWORD}}}))
    return credentials


def _staged_text(directory):
    text = ""
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), encoding="utf-8", errors="replace") as stream:
            text += stream.read()
    return text


class FrontendJobPublishesNoSecret(unittest.TestCase):
    def run_check(self, tmp, credentials):
        return subprocess.run([sys.executable, CHECK, "kde"], cwd=tmp, env=_env(tmp, credentials),
                              capture_output=True, text=True, check=False)

    def test_sentinels_reach_neither_staging_nor_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_check(tmp, _setup(tmp))
            staged = os.path.join(tmp, "e2e-publish")
            self.assertEqual(sorted(os.listdir(staged)),
                             ["e2e-recipe-kde.redacted.json", "e2e-recipe-kde.summary.json"])
            seen = result.stdout + result.stderr + _staged_text(staged)
            for sentinel in SENTINELS:
                for form in _forms(sentinel):
                    self.assertNotIn(form, seen)
            self.assertIn(publish.MARKER, result.stdout)
            self.assertIn("fisherman: encryption.passphrase", result.stderr)
            self.assertEqual(result.returncode, 1)
            # The full recipe stays where the shim kept it, not in the staging dir.
            self.assertFalse([n for n in os.listdir(tmp) if n.startswith("e2e-recipe-")])

    def test_summary_is_an_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_check(tmp, _setup(tmp))
            with open(os.path.join(tmp, "e2e-publish", "e2e-recipe-kde.summary.json")) as stream:
                summary = json.load(stream)
        self.assertEqual(summary["recipe"]["encryption"],
                         {"type": "luks-passphrase", "passphrase": publish.MARKER})
        self.assertEqual(summary["recipe"]["user"],
                         {"username": "e2euser", "groups": ["wheel"], "password": publish.MARKER})
        self.assertEqual(summary["withheld"], ["slurp", "user.fullname"])
        self.assertEqual(summary["redacted"], ["encryption.passphrase", "user.password"])

    def test_vm_job_restores_the_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            credentials = _setup(tmp)
            self.run_check(tmp, credentials)
            redacted = os.path.join(tmp, "e2e-publish", "e2e-recipe-kde.redacted.json")
            out = os.path.join(tmp, "private-recipe.json")
            result = subprocess.run(
                [sys.executable, CHECK, "--vm", redacted, "/dev/loop5", out, "--frontend", "kde"],
                cwd=tmp, env=_env(tmp, credentials), capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(out, "rb") as stream:
                self.assertEqual(stream.read(), RECIPE.replace(b"/dev/loop0", b"/dev/loop5"))
            for sentinel in SENTINELS:
                self.assertNotIn(sentinel, result.stdout + result.stderr)

    def test_vm_job_without_the_frontend_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            credentials = _setup(tmp)
            self.run_check(tmp, credentials)
            redacted = os.path.join(tmp, "e2e-publish", "e2e-recipe-kde.redacted.json")
            result = subprocess.run(
                [sys.executable, CHECK, "--vm", redacted, "/dev/loop5", os.path.join(tmp, "o.json")],
                cwd=tmp, env=_env(tmp, credentials), capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("test-credentials.json has no value", result.stderr)

    def test_a_secret_that_is_not_the_test_value_is_not_staged(self):
        """The frontend changed what the driver typed, or a driver uses a
        value that the credentials file does not have: the VM job could
        not restore the bytes, so no redacted copy and a failure."""
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_check(tmp, _setup(tmp, passphrase="other-value"))
            staged = os.path.join(tmp, "e2e-publish")
            self.assertEqual(os.listdir(staged), ["e2e-recipe-kde.summary.json"])
            self.assertIn("redacted recipe: a secret in the recipe is not the test value",
                          result.stderr)
            for sentinel in SENTINELS + ("other-value",):
                self.assertNotIn(sentinel, result.stdout + result.stderr + _staged_text(staged))


class Redaction(unittest.TestCase):
    def test_round_trip(self):
        redacted = publish.redact_bytes(RECIPE)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel.encode(), redacted)
        self.assertIn(b'"<redacted:encryption.passphrase>"', redacted)
        credentials = {"kde": {"encryption.passphrase": PASSPHRASE, "user.password": PASSWORD}}
        self.assertEqual(publish.restore_bytes(redacted, "kde", credentials), RECIPE)

    def test_a_secret_in_another_field_is_refused(self):
        leaky = RECIPE.replace(b'"e2e-host"', f'"{PASSWORD}-host"'.encode())
        with self.assertRaises(ValueError) as caught:
            publish.redact_bytes(leaky)
        self.assertNotIn(PASSWORD, str(caught.exception))

    def test_an_escaped_secret_is_refused(self):
        """A value that the frontend wrote with other escapes than
        json.dumps cannot be put back byte for byte."""
        escaped = RECIPE.replace(PASSWORD.encode(), PASSWORD.replace("-", "\\u002d").encode())
        with self.assertRaises(ValueError):
            publish.redact_bytes(escaped)

    def test_no_secret_no_change(self):
        plain = b'{"disk": "/dev/loop0", "encryption": {"type": "none"}}'
        self.assertEqual(publish.redact_bytes(plain), plain)


class StagingAllowlist(unittest.TestCase):
    def test_logs_are_redacted_and_other_files_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = os.path.join(tmp, "private")
            os.makedirs(private)
            recipe = os.path.join(private, "recipe.json")
            _write(recipe, RECIPE)
            logs = {"install.log": f"step 1\nluksFormat with {PASSPHRASE}\n",
                    "boot.log": f"typed {PASSPHRASE}\nuser {PASSWORD}\n",
                    "serial-e2e-kde-1.log": f"Please enter passphrase\n{PASSPHRASE}\n",
                    "swtpm-e2e-kde-1.log": "not on the allowlist\n",
                    "recipe-copy.json": RECIPE.decode()}
            paths = []
            for name, text in logs.items():
                paths.append(os.path.join(private, name))
                _write(paths[-1], text)
            staged = os.path.join(tmp, "out")
            result = subprocess.run(
                [sys.executable, PUBLISH, "stage", "--recipe", recipe, "--frontend", "kde",
                 "--out", staged, *paths, os.path.join(private, "missing.log")],
                capture_output=True, text=True, check=False,
                env={k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(os.listdir(staged)),
                             ["boot.log", "e2e-recipe-kde.summary.json", "install.log",
                              "serial-e2e-kde-1.log"])
            seen = result.stdout + result.stderr + _staged_text(staged)
            for sentinel in SENTINELS:
                for form in _forms(sentinel):
                    self.assertNotIn(form, seen)
            self.assertIn("luksFormat with <redacted>", _staged_text(staged))
            self.assertIn("not published (not on the allowlist): swtpm-e2e-kde-1.log", result.stdout)

    def test_redact_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = os.path.join(tmp, "recipe.json")
            _write(recipe, RECIPE)
            result = subprocess.run([sys.executable, PUBLISH, "redact-stream", "--recipe", recipe],
                                    input=f"a {PASSPHRASE} b\nc {PASSWORD}\n",
                                    capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "a <redacted> b\nc <redacted>\n")

    def test_a_long_log_keeps_both_ends(self):
        text = "FIRST FAILURE\n" + "x" * (publish.LOG_CAP * 2) + "\nLAST STATE\n"
        capped = publish._cap(text)
        self.assertLess(len(capped), publish.LOG_CAP + 200)
        self.assertTrue(capped.startswith("FIRST FAILURE") and capped.endswith("LAST STATE\n"))

    def test_write_staged_refuses_other_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("recipe.json", "e2e-recipe-kde.json", "../install.log"):
                with self.assertRaises(ValueError):
                    publish.write_staged(tmp, name, "x")


class SecretFieldsAreComplete(unittest.TestCase):
    def test_schema_secret_names_are_secret_fields(self):
        with open(os.path.join(REPO, "shared", "recipe", "fisherman-recipe.schema.json")) as stream:
            schema = json.load(stream)
        looks_secret = re.compile(r"pass|secret|token|credential|private|^key$|apikey", re.I)
        known = {f"{block}.{key}" for block, key in publish.SECRET_FIELDS}

        def walk(node, prefix=""):
            for name, sub in (node.get("properties") or {}).items():
                yield prefix + name, sub
                yield from walk(sub, prefix + name + ".")
                if isinstance(sub.get("items"), dict):
                    yield from walk(sub["items"], prefix + name + "[].")

        for path, _sub in walk(schema):
            if looks_secret.search(path.rsplit(".", 1)[-1]):
                self.assertIn(path, known, f"{path} looks like a secret: add it to SECRET_FIELDS")

    def test_summary_allowlist_names_schema_keys(self):
        with open(os.path.join(REPO, "shared", "recipe", "fisherman-recipe.schema.json")) as stream:
            properties = set(json.load(stream)["properties"])
        self.assertLessEqual(publish.SUMMARY_KEYS, properties)
        self.assertLessEqual(set(publish.SUMMARY_BLOCK_KEYS), properties)
        for block, _key in publish.SECRET_FIELDS:
            self.assertNotIn(block, publish.SUMMARY_KEYS)

    def test_test_credentials_are_the_drivers_values(self):
        drivers = {"gnome": "tests/e2e/run_gnome.py", "xfce": "frontends/xfce/tests/e2e/run.py",
                   "niri": "frontends/niri/tests/e2e/run.py", "kde": "frontends/kde/tests/e2e.cpp",
                   "cosmic": "frontends/cosmic/src/main.rs"}
        credentials = publish.load_credentials(publish.CREDENTIALS)
        self.assertEqual(set(credentials), set(drivers))
        for frontend, fields in credentials.items():
            with open(os.path.join(REPO, drivers[frontend]), encoding="utf-8") as stream:
                source = stream.read()
            for field, value in fields.items():
                self.assertIn(f'"{value}"', source, f"{frontend} {field}")


class PublishedDirectories(unittest.TestCase):
    def test_committed_walkthroughs_pass_the_audit(self):
        dirs = [os.path.join(REPO, d) for d in ("docs/walkthrough", "docs/screenshots")]
        dirs += [os.path.join(REPO, "frontends", fe, "docs", "screenshots")
                 for fe in ("kde", "cosmic", "niri", "xfce")]
        self.assertEqual(publish.audit_failures([d for d in dirs if os.path.isdir(d)]), [])

    def test_audit_catches_a_recipe_a_credential_and_a_file_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "walkthrough-x.json"), RECIPE)
            _write(os.path.join(tmp, "texts.json"), json.dumps({"page": "typed e2e-password"}))
            _write(os.path.join(tmp, "notes.txt"), "x")
            _write(os.path.join(tmp, "ok.json"), json.dumps({"passphrase": publish.MARKER}))
            failures = publish.audit_failures([tmp])
        self.assertEqual(len([f for f in failures if f.startswith("walkthrough-x.json")]), 2)
        self.assertTrue([f for f in failures if f.startswith("texts.json: holds")])
        self.assertTrue([f for f in failures if f.startswith("notes.txt")])
        self.assertFalse([f for f in failures if f.startswith("ok.json")])
        for failure in failures:
            for sentinel in SENTINELS + ("e2e-password",):
                self.assertNotIn(sentinel, failure)


class WorkflowsUploadOnlyStagedFiles(unittest.TestCase):
    def test_e2e_uploads(self):
        with open(os.path.join(REPO, ".github", "workflows", "e2e.yml")) as stream:
            text = stream.read()
        paths = re.findall(r"upload-artifact@\S+[^\n]*\n(?:\s+[^\n]*\n)*?\s+path: (\S+)", text)
        self.assertEqual(len(paths), 6, paths)
        for path in paths:
            self.assertTrue(path.endswith("e2e-publish/") or path == "/tmp/tuna-e2e-vm/", path)
        self.assertIn("e2e-recipe-${{ matrix.frontend }}.redacted.json", text)

    def test_vm_install_keeps_the_recipe_private(self):
        with open(os.path.join(E2E, "vm-install.sh")) as stream:
            code = "\n".join(line for line in stream.read().splitlines()
                             if not line.lstrip().startswith("#"))
        self.assertNotIn('"$OUT/recipe.json"', code)
        self.assertNotIn('tee "$OUT', code)
        self.assertIn('trap publish_and_clean EXIT', code)
        self.assertIn('export ARTIFACTS_DIR="$PRIV/bootcrew"', code)

    def test_walkthrough_audits_before_upload(self):
        with open(os.path.join(REPO, ".github", "workflows", "walkthrough.yml")) as stream:
            text = stream.read()
        self.assertLess(text.index("publish.py audit docs/walkthrough"),
                        text.index("name: walkthrough\n"))


if __name__ == "__main__":
    unittest.main()
