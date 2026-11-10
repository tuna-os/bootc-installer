#!/usr/bin/env python3
"""Judge the recipe a frontend handed to fisherman in the end-to-end job.

    check-recipe.py <frontend> [recipe.json] [--catalog images.json]
                                    (default recipe: /tmp/tuna-e2e/recipe.json)

Independent verdicts, all required:
  * the REAL fisherman accepts it (`fisherman validate --json -`, the same
    rules an install runs before it touches a disk), and each problem is
    reported with its stable code;
  * it conforms to shared/recipe/fisherman-recipe.schema.json, the contract
    the five frontends write against;
  * it targets the disk the job set up, so a frontend that picked the wrong
    device is caught here and not by a partitioned runner;
  * it leaves SELinux on (selinuxDisabled is not true);
  * the account follows the catalog contract (shared/catalog/README.md):
    the recipe creates a user, in wheel, exactly when the image needs one.
    The catalog is `--catalog`, else <e2e dir>/catalog.json, which the
    frontend's driver writes: the catalog it gave the frontend. A driver
    that does not export one yet is judged by LEGACY_USER_STEP.
The recipe is then copied to e2e-recipe-<frontend>.json for the VM job.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL = "/usr/local/lib/tuna-e2e/fisherman.real"
E2E_DIR = os.environ.get("TUNA_E2E_DIR", "/tmp/tuna-e2e")
# TODO(#288): remove once every driver writes <e2e dir>/catalog.json. Until
# then these three drivers, which do not export the catalog they used, keep
# the old verdict: their wizard always asks for an account, so the recipe
# must create one. GNOME's and XFCE's drivers use a catalog that says
# needs_user_creation is false and export nothing, so with no catalog their
# account is not judged (and the output says so).
LEGACY_USER_STEP = {"cosmic", "kde", "niri"}


def _catalog_resolver():
    spec = importlib.util.spec_from_file_location(
        "shared_catalog_resolve", os.path.join(REPO, "shared", "catalog", "resolve.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def account_required(frontend, recipe, catalog):
    """Whether the recipe must create an account: True, False, or None when
    nothing here can tell (no catalog, and no legacy rule for the frontend).

    With a catalog the answer is the contract's: the flag of the leaf the
    recipe installs, looked up by the image updates track (`targetImgref`,
    which is the catalog identity even when the source is an NVIDIA or a
    local image), then by `image`; an image the catalog does not have needs
    an account.
    """
    if catalog is None:
        return True if frontend in LEGACY_USER_STEP else None
    resolver = _catalog_resolver()
    refs = [ref for ref in (recipe.get("targetImgref"), recipe.get("image")) if ref]
    for ref in refs:
        leaf = resolver.find(catalog, ref)
        if leaf is None:
            # The NVIDIA variant of a leaf is that leaf.
            leaf = next((candidate for candidate in resolver.leaves(catalog)
                         if candidate["nvidia_imgref"] == ref), None)
        if leaf is not None:
            return leaf["needs_user_creation"]
    return True


def account_failures(frontend, recipe, catalog):
    """Problems with the recipe's `user` against the account contract."""
    required = account_required(frontend, recipe, catalog)
    user = recipe.get("user") or {}
    username = user.get("username") if isinstance(user, dict) else None
    if required is None:
        return []
    if required:
        if not username:
            return ["user: the image needs an account and the recipe has no username"]
        if "wheel" not in (user.get("groups") or []):
            return [f"user: {username!r} is not in wheel: {user.get('groups')!r}"]
        return []
    if username:
        return [f"user: the catalog says the image needs no account "
                f"(needs_user_creation is false) and the recipe creates {username!r}"]
    return []


def load_catalog(explicit=None):
    """The catalog the driver gave the frontend, or None when none is exported."""
    path = explicit or os.path.join(E2E_DIR, "catalog.json")
    if not explicit and not os.path.exists(path):
        return None
    return _catalog_resolver().load(path)


def main():
    args = sys.argv[1:]
    catalog_path = None
    if "--catalog" in args:
        at = args.index("--catalog")
        if at + 1 >= len(args):
            sys.exit(__doc__)
        catalog_path = args[at + 1]
        del args[at:at + 2]
    if not args:
        sys.exit(__doc__)
    frontend = args[0]
    path = args[1] if len(args) > 1 else os.path.join(E2E_DIR, "recipe.json")
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} does not exist: the frontend never launched fisherman")
    with open(path) as fh:
        recipe = json.load(fh)
    print(f"recipe from {frontend}:")
    print(json.dumps(recipe, indent=2))

    failures = []

    # `validate --json -`: every problem, with its stable code, from the
    # rules the install runs before it touches a disk. The recipe goes on
    # stdin, the way the frontends hand it over.
    with open(path, "rb") as fh:
        r = subprocess.run([REAL, "validate", "--json", "-"], stdin=fh,
                           capture_output=True, text=True, check=False)
    print(f"fisherman validate --json -> exit {r.returncode}")
    try:
        verdict = json.loads(r.stdout)
    except ValueError:
        verdict = None
    if r.returncode not in (0, 1) or not isinstance(verdict, dict):
        failures.append(f"fisherman validate --json failed: {(r.stdout + r.stderr).strip()}")
    else:
        for problem in verdict.get("errors") or []:
            failures.append(f"fisherman: {problem.get('field') or '<recipe>'}: "
                            f"{problem.get('code')}: {problem.get('message')}")
        if verdict.get("valid"):
            print("fisherman validate: ok")

    try:
        import jsonschema
        with open(os.path.join(REPO, "shared", "recipe", "fisherman-recipe.schema.json")) as fh:
            schema = json.load(fh)
        errors = sorted(jsonschema.Draft7Validator(schema).iter_errors(recipe), key=str)
        for e in errors:
            failures.append(f"schema: {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}")
        if not errors:
            print("schema: ok")
    except ImportError:
        failures.append("python3-jsonschema is not installed; the schema was not checked")

    expected = ""
    try:
        with open(os.path.join(E2E_DIR, "loopdev")) as fh:
            expected = fh.read().strip()
    except OSError:
        pass
    if expected and recipe.get("disk") != expected:
        failures.append(f"disk: frontend chose {recipe.get('disk')!r}, the e2e disk is {expected!r}")
    if not recipe.get("hostname"):
        failures.append("hostname is empty")
    if recipe.get("encryption", {}).get("type") not in ("none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"):
        failures.append(f"encryption type {recipe.get('encryption')!r}")
    # selinuxDisabled=true makes bootc add selinux=0 to the installed
    # system's kernel arguments. Four frontends once hardcoded it (#160).
    if recipe.get("selinuxDisabled") is True:
        failures.append("selinuxDisabled is true: the installed system would boot with selinux=0")
    try:
        catalog = load_catalog(catalog_path)
    except (OSError, ValueError) as error:
        catalog = None
        failures.append(f"catalog: {error}")
    required = account_required(frontend, recipe, catalog)
    if catalog is None and required is None:
        print(f"account: NOT JUDGED. The {frontend} driver exports no catalog "
              f"({os.path.join(E2E_DIR, 'catalog.json')}); see shared/e2e/README.md")
    else:
        source = "the catalog" if catalog is not None else "the legacy rule for this frontend"
        print(f"account: {'required' if required else 'not wanted'} by {source}")
    failures.extend(account_failures(frontend, recipe, catalog))

    out = f"e2e-recipe-{frontend}.json"
    shutil.copyfile(path, out)
    print(f"kept as {out}")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"OK: {frontend} produced a recipe the real fisherman accepts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
