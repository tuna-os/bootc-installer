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
    frontend's driver writes: the catalog it gave the frontend. Every
    driver gives its frontend shared/e2e/catalog.json, so an exported
    catalog with other content fails. A driver that does not export one
    is judged by LEGACY_USER_STEP;
  * the desktop extras follow the same catalog: the recipe has the `extras`
    object of the leaf it installs, or no key when the leaf has none. The
    shim has no catalog, as a fisherman that a Flatpak stages has none, so
    a frontend that drops the object installs a system without the steps.
The recipe is then copied to e2e-recipe-<frontend>.json for the VM job.

    check-recipe.py --vm <e2e-recipe-<frontend>.json> <loop device> <out.json>

The VM job's mode (vm-install.sh). It writes the recipe that the VM job
installs, and proves that it is the frontend's recipe: the same bytes, with
at most one substitution, the value of `disk`. The disk is the only value
the frontend cannot know: it is the loop device of another runner. When
that device path is the same here (vm-install.sh attaches the disk there
when it is free), the copy is byte for byte. Any other difference fails.
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
# The catalog every E2E driver gives its frontend (README.md, "The catalog").
SHARED_CATALOG = os.path.join(REPO, "shared", "e2e", "catalog.json")
# Every driver now writes <e2e dir>/catalog.json, so this set is empty. A
# frontend named here would keep the old verdict (the recipe must create an
# account) when no catalog is exported. With no catalog, an account is not
# judged, and the output says so.
LEGACY_USER_STEP = set()


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
        # The NVIDIA variant of a leaf is that leaf (resolver.find).
        leaf = resolver.find(catalog, ref)
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
        return [("user: the catalog says the image needs no account "
                 f"(needs_user_creation is false) and the recipe creates {username!r}")]
    return []


def catalog_leaf(recipe, catalog):
    """The catalog leaf that the recipe installs, or None."""
    resolver = _catalog_resolver()
    for ref in (recipe.get("targetImgref"), recipe.get("image")):
        if not ref:
            continue
        leaf = resolver.find(catalog, ref)
        if leaf is None:
            leaf = next((candidate for candidate in resolver.leaves(catalog)
                         if candidate["nvidia_imgref"] == ref), None)
        if leaf is not None:
            return leaf
    return None


def extras_failures(recipe, catalog):
    """Problems with the recipe's `extras` against the catalog contract
    (shared/catalog/README.md, "Desktop extras"). [] with no catalog, or
    for an image that the catalog does not have."""
    if catalog is None:
        return []
    leaf = catalog_leaf(recipe, catalog)
    if leaf is None:
        return []
    resolver = _catalog_resolver()
    if leaf["extras"] is None:
        if "extras" in recipe:
            return [f"extras: the catalog leaf has none and the recipe has {recipe['extras']!r}"]
        return []
    fragment = {"recipe": {"extras": leaf["extras"]}, "absent": []}
    return resolver.recipe_matches(recipe, fragment)


def load_catalog(explicit=None):
    """The catalog the driver gave the frontend, or None when none is exported."""
    path = explicit or os.path.join(E2E_DIR, "catalog.json")
    if not explicit and not os.path.exists(path):
        return None
    return _catalog_resolver().load(path)


def shared_catalog_failures(catalog, explicit=None):
    """The exported catalog must be the shared one: one catalog for the
    five drivers, so each VM run's account follows the leaf the driver
    chose, and not a catalog of the driver's own. `--catalog` is the job's
    own choice and is not held to it."""
    if catalog is None or explicit:
        return []
    with open(SHARED_CATALOG, encoding="utf-8") as fh:
        shared = json.load(fh)
    if catalog != shared:
        return [f"catalog: the driver exported a catalog that is not {SHARED_CATALOG}"]
    return []


_ABSENT = object()


def vm_recipe(frontend_bytes, loopdev):
    """The recipe the VM job installs: `frontend_bytes`, with the JSON
    string of the old `disk` value replaced by `loopdev`. Raises ValueError
    when that string is not in the bytes exactly once."""
    recipe = json.loads(frontend_bytes)
    old = recipe.get("disk")
    if not isinstance(old, str) or not old:
        raise ValueError(f"disk: the frontend's recipe has no disk: {old!r}")
    if old == loopdev:
        return frontend_bytes
    old_token = json.dumps(old).encode()
    if frontend_bytes.count(old_token) != 1:
        raise ValueError(f"disk: {old!r} is in the recipe {frontend_bytes.count(old_token)} "
                         "times, so the one substitution is not safe")
    return frontend_bytes.replace(old_token, json.dumps(loopdev).encode())


def vm_recipe_failures(frontend_bytes, vm_bytes, loopdev):
    """Problems with the VM job's recipe against the frontend's: [] when it
    is the frontend's bytes with only `disk` set to `loopdev`."""
    try:
        frontend = json.loads(frontend_bytes)
        vm = json.loads(vm_bytes)
    except ValueError as error:
        return [f"vm recipe: not JSON: {error}"]
    failures = []
    if vm.get("disk") != loopdev:
        failures.append(f"vm recipe: disk is {vm.get('disk')!r}, not the loop device {loopdev!r}")
    changed = sorted(key for key in set(frontend) | set(vm)
                     if key != "disk" and frontend.get(key, _ABSENT) != vm.get(key, _ABSENT))
    if changed:
        failures.append(f"vm recipe: the VM job changed {', '.join(changed)}: only disk may differ")
    try:
        expected = vm_recipe(frontend_bytes, loopdev)
    except ValueError as error:
        failures.append(f"vm recipe: {error}")
    else:
        if vm_bytes != expected:
            failures.append("vm recipe: the bytes differ from the frontend's in more than the disk value")
    return failures


def vm_main(args):
    """`--vm <frontend recipe> <loop device> <out>`: see the module doc."""
    if len(args) != 3:
        sys.exit(__doc__)
    source, loopdev, out = args
    with open(source, "rb") as fh:
        frontend_bytes = fh.read()
    try:
        vm_bytes = vm_recipe(frontend_bytes, loopdev)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    with open(out, "wb") as fh:
        fh.write(vm_bytes)
    with open(out, "rb") as fh:
        written = fh.read()
    failures = vm_recipe_failures(frontend_bytes, written, loopdev)
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    old = json.loads(frontend_bytes).get("disk")
    if written == frontend_bytes:
        print(f"vm recipe: byte for byte the frontend's recipe (disk {old} is free here too)")
    else:
        print(f"vm recipe: the frontend's recipe, byte for byte, except disk {old} -> {loopdev}")
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--vm"]:
        return vm_main(args[1:])
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
    failures.extend(shared_catalog_failures(catalog, catalog_path))
    required = account_required(frontend, recipe, catalog)
    if catalog is None and required is None:
        print(f"account: NOT JUDGED. The {frontend} driver exports no catalog "
              f"({os.path.join(E2E_DIR, 'catalog.json')}); see shared/e2e/README.md")
    else:
        source = "the catalog" if catalog is not None else "the legacy rule for this frontend"
        print(f"account: {'required' if required else 'not wanted'} by {source}")
    failures.extend(account_failures(frontend, recipe, catalog))
    extras = extras_failures(recipe, catalog)
    if catalog is not None and not extras:
        print(f"extras: {recipe.get('extras', 'no key')!r}, as the catalog says")
    failures.extend(extras)

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
