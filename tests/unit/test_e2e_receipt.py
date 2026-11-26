"""Evidence receipts of the walkthrough and the VM canary (#270).

Positive fixtures map the existing outputs to valid receipts with their
own evidence class. Negative controls show that the rules reject: a
canary relabelled as installed media, a skipped or unknown required
assertion read as a pass, a missing artifact, a lost first failure, a
blind retry of a secret action, a secret in the receipt.
"""
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
E2E = os.path.join(REPO, "shared", "e2e")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


receipt = _load("e2e_receipt", os.path.join(E2E, "receipt.py"))
publish = _load("e2e_publish_r", os.path.join(E2E, "publish.py"))

IDENT = dict(run_id="42", attempt=1, session="s1", source_revision="a" * 40,
             harness_revision="a" * 40)
REPORT = {
    "flavor": "gnome", "ocr": False, "text_source": "widget-tree",
    "activation_key": None, "strict": True, "failures": 0, "failure_reasons": [],
    "contract_digest": "d" * 64,
    "screen_outcomes": {"welcome": "passed", "disk": "passed",
                        "network": {"outcome": "exempt", "reason": "the live image has no network page"}},
    "pages": [{"name": "welcome", "png": "/x/01-welcome.png", "sha256": "1" * 64}],
}


def canary(install=True, boot=True, cleanup=None, staged=()):
    return receipt.from_canary("gnome", install, boot, cleanup or {"outcome": "ok"},
                               list(staged), **IDENT)


class Walkthrough(unittest.TestCase):
    def test_maps_with_its_own_labels(self):
        r = receipt.from_walkthrough(REPORT, **IDENT)
        self.assertEqual(receipt.validate(r), [])
        self.assertEqual(r["evidence_class"], "programmatic-capture")
        self.assertEqual(r["observation"]["semantic"], "widget-tree")
        self.assertIs(r["observation"]["ocr"], False)
        self.assertIsNone(r["observation"]["activation_key"])   # unknown stays unknown
        self.assertIsNone(r["observation"]["backend_outcome"])
        self.assertEqual(r["outcome"], "passed")

    def test_exemption_is_unsupported_with_reason(self):
        r = receipt.from_walkthrough(REPORT, **IDENT)
        net = [a for a in r["assertions"] if a["id"] == "screen:network"][0]
        self.assertEqual(net["outcome"], "unsupported")
        self.assertIn("no network page", net["reason"])
        net["reason"] = " "
        self.assertTrue(any("needs a reason" in p for p in receipt.validate(r)))

    def test_failed_screen_is_not_a_pass(self):
        rep = copy.deepcopy(REPORT)
        rep["screen_outcomes"]["disk"] = "failed"
        r = receipt.from_walkthrough(rep, **IDENT)
        self.assertEqual(r["outcome"], "failed")
        r["outcome"] = "passed"
        self.assertTrue(any("required assertions" in p for p in receipt.validate(r)))

    def test_not_measured_is_not_a_pass(self):
        rep = copy.deepcopy(REPORT)
        rep["screen_outcomes"]["disk"] = "not-measured"
        self.assertEqual(receipt.from_walkthrough(rep, **IDENT)["outcome"], "not-run")

    def test_unknown_outcome_is_rejected(self):
        r = receipt.from_walkthrough(REPORT, **IDENT)
        r["assertions"][0]["outcome"] = None
        self.assertTrue(any("unknown" in p for p in receipt.validate(r)))

    def test_missing_png_hash_is_a_missing_artifact(self):
        rep = copy.deepcopy(REPORT)
        rep["pages"][0]["sha256"] = None
        r = receipt.from_walkthrough(rep, **IDENT)
        self.assertTrue(any("mandatory artifact" in p for p in receipt.validate(r)))


class Canary(unittest.TestCase):
    def test_positive_fixture(self):
        r = canary()
        self.assertEqual(receipt.validate(r, claim="modified-canary"), [])
        self.assertEqual(r["outcome"], "passed")
        kinds = {m["kind"] for m in r["modifications"]}
        self.assertTrue({"ssh-enabled", "kernel-arguments", "image"} <= kinds)

    def test_cannot_be_relabelled_as_installed_media(self):
        r = canary()
        self.assertTrue(any("cannot stand for installed-media" in p
                            for p in receipt.validate(r, claim="installed-media")))
        r["evidence_class"] = "installed-media"   # relabel: the modifications give it away
        self.assertTrue(any("cannot carry modifications" in p for p in receipt.validate(r)))
        r["modifications"] = []                   # and without them, no image digest
        self.assertTrue(any("image digest" in p
                            for p in receipt.validate(r, claim="installed-media")))

    def test_modified_canary_needs_its_modifications(self):
        r = canary()
        r["modifications"] = []
        self.assertTrue(any("must list its modifications" in p for p in receipt.validate(r)))

    def test_boot_not_run_after_install_failure(self):
        r = canary(install=False, boot=False)
        self.assertEqual(r["outcome"], "failed")
        self.assertEqual([a["outcome"] for a in r["assertions"]], ["failed", "not-run"])

    def test_cleanup_failure_stays_visible(self):
        r = canary(cleanup={"outcome": "failed", "detail": "loop device"})
        self.assertEqual(r["outcome"], "failed")
        self.assertEqual(r["cleanup"]["detail"], "loop device")
        r["outcome"] = "passed"
        self.assertTrue(any("cleanup failed" in p for p in receipt.validate(r)))

    def test_original_failure_survives_a_failed_cleanup(self):
        r = canary(install=False, boot=False, cleanup={"outcome": "failed"})
        self.assertEqual(r["assertions"][0]["outcome"], "failed")
        self.assertEqual(r["cleanup"]["outcome"], "failed")

    def test_receipt_is_final_only_after_teardown(self):
        r = canary()
        r["cleanup"] = None
        self.assertTrue(any("cleanup is not recorded" in p for p in receipt.validate(r)))

    def test_identity_is_required(self):
        r = canary()
        r["identity"]["session"] = ""
        self.assertTrue(any("identity.session" in p for p in receipt.validate(r)))

    def test_unknown_version(self):
        r = canary()
        r["version"] = 2
        self.assertTrue(receipt.validate(r))


class Attempts(unittest.TestCase):
    def test_pass_after_failure_keeps_lineage_as_flaky(self):
        r = canary()
        r["attempts"] = [{"n": 1, "outcome": "failed", "reason": "no paint"},
                         {"n": 2, "outcome": "passed"}]
        self.assertTrue(any("flaky" in p for p in receipt.validate(r)))
        r["outcome"] = "flaky"
        self.assertEqual(receipt.validate(r), [])

    def test_secret_action_is_not_retried(self):
        r = canary()
        r["outcome"] = "failed"
        r["attempts"] = [{"n": 1, "kind": "secret", "action": "type-passphrase", "outcome": "failed"},
                         {"n": 2, "kind": "secret", "action": "type-passphrase", "outcome": "failed"}]
        self.assertTrue(any("was retried" in p for p in receipt.validate(r)))


class Artifacts(unittest.TestCase):
    def test_hash_mismatch_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "install.log")
            open(path, "w").write("ok\n")
            item = receipt.artifact(path)
            self.assertEqual(item["sha256"], hashlib.sha256(b"ok\n").hexdigest())
            r = canary(staged=[item])
            self.assertEqual(receipt.validate(r, artifact_dir=d), [])
            open(path, "w").write("changed\n")
            self.assertTrue(any("does not match" in p for p in receipt.validate(r, artifact_dir=d)))
            gone = receipt.artifact(os.path.join(d, "boot.log"))
            self.assertIsNone(gone["sha256"])
            self.assertTrue(any("missing" in p for p in receipt.validate(canary(staged=[gone]))))

    def test_a_missing_capability_does_not_block_another(self):
        bad = receipt.from_walkthrough(REPORT, **IDENT)
        bad["identity"]["run_id"] = ""
        good = canary()
        self.assertTrue(receipt.validate(bad))
        self.assertEqual(receipt.validate(good), [])


class SecretSafety(unittest.TestCase):
    SENTINEL = "SENTINEL-luks-7f3a9c"

    def test_receipt_holds_no_secret(self):
        with tempfile.TemporaryDirectory() as d:
            priv, out = os.path.join(d, "priv"), os.path.join(d, "out")
            os.makedirs(priv)
            recipe = os.path.join(priv, "recipe.json")
            json.dump({"disk": "/dev/loop0", "encryption": {"type": "luks-passphrase",
                       "passphrase": self.SENTINEL}}, open(recipe, "w"))
            log = os.path.join(priv, "install.log")
            open(log, "w").write(f"passphrase {self.SENTINEL}\n")
            publish.stage(recipe, "gnome", out, [log])
            staged = [receipt.artifact(os.path.join(out, n), mandatory=n == "install.log")
                      for n in sorted(os.listdir(out))]
            r = canary(staged=staged)
            self.assertEqual(receipt.validate(r, secrets=[self.SENTINEL]), [])
            path = os.path.join(out, "receipt-gnome.json")
            json.dump(r, open(path, "w"))
            only = os.path.join(d, "only")
            os.makedirs(only)
            os.replace(path, os.path.join(only, "receipt-gnome.json"))
            self.assertEqual(publish.audit_failures([only], credentials={}), [])
            for top in (out, only):
                for name in os.listdir(top):
                    self.assertNotIn(self.SENTINEL, open(os.path.join(top, name)).read())
            r["assertions"][0]["inputs"] = {"log": self.SENTINEL}
            self.assertTrue(any("secret" in p for p in
                                receipt.validate(r, secrets=[self.SENTINEL])))

    def test_receipt_is_on_the_publication_allowlist(self):
        self.assertTrue(publish._matches("receipt-gnome.json", publish.STAGE_ALLOWLIST))


class Cli(unittest.TestCase):
    def test_walkthrough_and_validate(self):
        with tempfile.TemporaryDirectory() as d:
            rep, out = os.path.join(d, "walkthrough-gnome.json"), os.path.join(d, "r.json")
            json.dump(REPORT, open(rep, "w"))
            def run(*a):
                return subprocess.run([sys.executable, "-I", os.path.join(E2E, "receipt.py"), *a],
                                                        capture_output=True, text=True)
            self.assertEqual(run("walkthrough", rep, "--out", out, "--run-id", "9").returncode, 0)
            self.assertEqual(run("validate", out).returncode, 0)
            self.assertEqual(run("validate", out, "--claim", "installed-media").returncode, 1)

    def test_canary_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "r.json")
            p = subprocess.run([sys.executable, "-I", os.path.join(E2E, "receipt.py"), "canary",
                                "--frontend", "xfce", "--install-ok", "--cleanup", "failed",
                                "--out", out, "--run-id", "9"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            r = json.load(open(out))
            self.assertEqual(r["outcome"], "failed")
            self.assertEqual(r["assertions"][1]["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
