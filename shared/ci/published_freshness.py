#!/usr/bin/env python3
"""Is every frontend's published Flatpak the build `prod` last released?

The tuna-os Flatpak remote resolves installs through one static index
(https://tunaos.org/flatpak/index/static, the URL docs/RELEASE.md gives
downstreams). release.yml publishes each frontend to the one package
ghcr.io/tuna-os/bootc-installer, tagged with the frontend name
(publish-oci.yml), and updates that index. This script reads the index and
says, per frontend, whether what it serves is what `prod` should have
published. Issue #158 is the failure it exists to catch: four frontends kept
being served from the orphaned pre-migration entries
tuna-os/tuna-installer-{kde,cosmic,niri,xfce}, and nothing noticed.

What the index carries, per image (one per architecture):
  Name (the registry repository), Tags, Architecture, Digest, and the Flatpak
  labels, of which three matter here:
    org.flatpak.ref        app/<app id>/<arch>/<branch>
    org.flatpak.subject    "Built from <40-hex git sha>" (the commit the
                           publishing workflow ran on)
    org.flatpak.timestamp  build time, unix seconds
The index has no OCI revision/created label, so the source commit comes from
org.flatpak.subject. When a subject does not carry a sha the check falls back
to the timestamp: the image must be newer than the last commit that changed
that frontend's tree up to the released commit. That fallback cannot tell two
builds of the same tree apart; the sha comparison can.

What "should have been published" means mirrors release.yml exactly:
release.yml republishes a frontend only when its tree changed since the
previous release, so the served commit need not BE the released commit. It
must be on prod, and either an ancestor of the released commit with no
change to that frontend's tree in between, using release.yml's own path rule
(gnome: anything outside frontends/, docs/ and top-level *.md; the others:
frontends/<name>/), or newer than it (a release still publishing, or the
hand-dispatched republish on prod that docs/RELEASE.md lists).

The released commit is the head of the last successful release.yml run on
prod. If prod HEAD has changes to a frontend that its served build does not
cover and the newest release run on prod has finished without publishing
them, that frontend is stale too.
A release still queued or running is reported, not failed.

Exit status: 0 everything is fresh, 1 something is stale, 2 the check itself
could not run. Run it locally from a clone that has origin/prod fetched:

    python3 shared/ci/published_freshness.py --git-dir . --prod-ref origin/prod
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field

INDEX_URL = "https://tunaos.org/flatpak/index/static"
PACKAGE = "tuna-os/bootc-installer"
LEGACY_PREFIX = "tuna-os/tuna-installer-"
FRONTENDS = ("gnome", "kde", "cosmic", "niri", "xfce")
APP_IDS = {
    "gnome": "org.bootcinstaller.Installer",
    "kde": "org.tunaos.InstallerKde",
    "cosmic": "org.tunaos.InstallerCosmic",
    "niri": "org.tunaos.InstallerNiri",
    "xfce": "org.tunaos.InstallerXfce",
}
# publish-flatpak*.yml publish x86_64 and aarch64; the index names them in
# OCI terms.
ARCHS = ("amd64", "arm64")

_SUBJECT_SHA = re.compile(r"\bBuilt from ([0-9a-f]{40})\b")
_GNOME_EXCLUDED = re.compile(r"^(frontends/|docs/|README\.md|[^/]+\.md$)")


# ---------------------------------------------------------------- pure logic


@dataclass
class Image:
    repo: str
    arch: str
    tags: list
    digest: str
    app_ref: str
    timestamp: int | None
    commit: str | None

    @property
    def app_id(self) -> str:
        parts = self.app_ref.split("/")
        return parts[1] if len(parts) > 1 else ""


@dataclass
class Verdict:
    frontend: str
    stale: bool
    reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    served: list = field(default_factory=list)


def parse_index(doc: dict) -> list:
    """Flatten the index into one Image per (repository, architecture)."""
    images = []
    for result in doc.get("Results") or []:
        repo = result.get("Name", "")
        for img in result.get("Images") or []:
            labels = img.get("Labels") or {}
            m = _SUBJECT_SHA.search(labels.get("org.flatpak.subject", ""))
            ts = labels.get("org.flatpak.timestamp")
            images.append(
                Image(
                    repo=repo,
                    arch=img.get("Architecture", ""),
                    tags=list(img.get("Tags") or []),
                    digest=img.get("Digest", ""),
                    app_ref=labels.get("org.flatpak.ref", ""),
                    timestamp=int(ts) if ts and str(ts).isdigit() else None,
                    commit=m.group(1) if m else None,
                )
            )
    return images


def touches(frontend: str, paths) -> list:
    """The paths release.yml would count as a change to this frontend."""
    if frontend == "gnome":
        return [p for p in paths if p and not _GNOME_EXCLUDED.match(p)]
    prefix = f"frontends/{frontend}/"
    return [p for p in paths if p.startswith(prefix)]


def served_images(frontend: str, images) -> tuple:
    """(current-package images, legacy-entry images) serving this frontend."""
    app_id = APP_IDS[frontend]
    current = [i for i in images if i.repo == PACKAGE and frontend in i.tags]
    legacy = [
        i
        for i in images
        if i.repo.startswith(LEGACY_PREFIX)
        and (i.repo == LEGACY_PREFIX + frontend or i.app_id == app_id)
    ]
    return current, legacy


def _short(sha):
    return (sha or "?")[:7]


def _when(ts):
    if ts is None:
        return "unknown time"
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def evaluate(frontend, images, released, history):
    """Decide whether one frontend is stale.

    released: {"sha", "prod_head", "latest_run": {"head_sha", "status",
    "conclusion"}} or released["sha"] None when no release run succeeded.
    history: an object with
      is_ancestor(a, b) -> bool | None (None: commit unknown here)
      changed(a, b)     -> list of paths
      last_change_time(frontend, sha) -> unix seconds | None
    """
    v = Verdict(frontend=frontend, stale=False)
    current, legacy = served_images(frontend, images)
    v.served = current + legacy

    for repo in sorted({i.repo for i in legacy}):
        imgs = [i for i in legacy if i.repo == repo]
        archs = "/".join(i.arch for i in imgs)
        built = min((i.timestamp for i in imgs if i.timestamp), default=None)
        commits = ", ".join(sorted({_short(i.commit) for i in imgs}))
        v.reasons.append(
            f"served from orphaned pre-migration entry `{repo}` ({archs}, "
            f"`{imgs[0].app_id}`, built {_when(built)} from {commits}); "
            f"nothing publishes there any more"
        )

    if not current:
        v.reasons.append(f"no `{PACKAGE}` entry tagged `{frontend}` in the index")
    else:
        for arch in ARCHS:
            if not any(i.arch == arch for i in current):
                v.reasons.append(f"`{PACKAGE}:{frontend}` has no {arch} image in the index")
        for img in current:
            if img.app_id != APP_IDS[frontend]:
                v.reasons.append(
                    f"`{PACKAGE}:{frontend}` ({img.arch}) carries `{img.app_ref}`, "
                    f"expected app id `{APP_IDS[frontend]}`"
                )

    rel = released.get("sha")
    if not rel:
        v.reasons.append("no successful release.yml run on prod to compare against")
    else:
        bases = {rel}
        for img in current:
            base = _check_image(v, img, rel, released.get("prod_head"), history)
            if base:
                bases.add(base)
        # The pending check starts from the newest commit already served:
        # an image built after the last successful release (a release still
        # publishing, or a hand-dispatched publish on prod) already covers
        # what it was built from.
        newest = [b for b in bases if all(history.is_ancestor(o, b) for o in bases)]
        _check_pending(v, released, newest[0] if newest else rel, history)

    v.stale = bool(v.reasons)
    return v


def _check_image(v, img, rel, head, history):
    """Check one served image; return its commit when it is newer than rel."""
    fe = v.frontend
    label = f"`{PACKAGE}:{fe}` ({img.arch})"
    if img.commit is None:
        # No sha in the subject: fall back to the build time.
        newest = history.last_change_time(fe, rel)
        if img.timestamp is None:
            v.reasons.append(f"{label} carries neither a source commit nor a build time")
        elif newest is not None and img.timestamp < newest:
            v.reasons.append(
                f"{label} was built {_when(img.timestamp)}, before the last {fe} "
                f"change released in {_short(rel)} ({_when(newest)}); the index "
                f"has no source commit for this image, so this is a time comparison"
            )
        return None
    if img.commit == rel:
        return None
    on_prod = history.is_ancestor(img.commit, head or rel)
    if on_prod is None:
        v.reasons.append(f"{label} was built from {_short(img.commit)}, which is not in this repository")
        return None
    if not on_prod:
        v.reasons.append(f"{label} was built from {_short(img.commit)}, which is not on prod")
        return None
    if history.is_ancestor(rel, img.commit):
        # Newer than the last successful release, and on prod.
        return img.commit
    diff = touches(fe, history.changed(img.commit, rel))
    if diff:
        sample = ", ".join(f"`{p}`" for p in diff[:3]) + (" ..." if len(diff) > 3 else "")
        v.reasons.append(
            f"{label} was built from {_short(img.commit)}; the release at "
            f"{_short(rel)} has {len(diff)} later {fe} file change(s) ({sample}) "
            f"that were never published"
        )
    return None


def _check_pending(v, released, base, history):
    fe = v.frontend
    rel, head = released.get("sha"), released.get("prod_head")
    if not head or head == base:
        return
    diff = touches(fe, history.changed(base, head))
    if not diff:
        return
    run = released.get("latest_run") or {}
    if run.get("head_sha") == head and run.get("status") != "completed":
        v.notes.append(
            f"prod HEAD {_short(head)} has {fe} changes; its release run is {run.get('status')}"
        )
        return
    if run.get("status") != "completed":
        v.notes.append(
            f"prod HEAD {_short(head)} has {fe} changes; a release run is {run.get('status')}"
        )
        return
    if run.get("head_sha") == head:
        why = f"its release run ended `{run.get('conclusion')}`"
    else:
        why = (
            f"no release run was started for it (the newest is for "
            f"{_short(run.get('head_sha'))})"
        )
    v.reasons.append(
        f"prod HEAD {_short(head)} has {len(diff)} {fe} file change(s) not yet "
        f"published (last successful release {_short(rel)}), and {why}"
    )


def render(verdicts, released, index_url) -> str:
    stale = [v for v in verdicts if v.stale]
    lines = [
        "## Published Flatpak freshness",
        "",
        f"- index: {index_url}",
        f"- prod HEAD: `{_short(released.get('prod_head'))}`",
        f"- last successful release.yml on prod: `{_short(released.get('sha'))}`",
        "",
        "| frontend | state | served from |",
        "|---|---|---|",
    ]
    for v in verdicts:
        where = ", ".join(
            sorted({f"`{i.repo}` {i.arch} {_short(i.commit)}" for i in v.served})
        ) or "nothing"
        lines.append(f"| {v.frontend} | {'**stale**' if v.stale else 'fresh'} | {where} |")
    lines.append("")
    for v in verdicts:
        if v.reasons or v.notes:
            lines.append(f"### {v.frontend}")
            lines.extend(f"- {r}" for r in v.reasons)
            lines.extend(f"- note: {n}" for n in v.notes)
            lines.append("")
    lines.append(
        f"**{len(stale)} of {len(verdicts)} frontends stale**: "
        + (", ".join(v.frontend for v in stale) if stale else "none")
    )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ I/O adapters


class GitHistory:
    def __init__(self, git_dir):
        self.git_dir = git_dir

    def _git(self, *args, check=True):
        return subprocess.run(
            ["git", "-C", self.git_dir, *args], capture_output=True, text=True, check=check
        )

    def _known(self, sha):
        return self._git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def rev_parse(self, ref):
        return self._git("rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()

    def is_ancestor(self, a, b):
        if not (self._known(a) and self._known(b)):
            return None
        return self._git("merge-base", "--is-ancestor", a, b, check=False).returncode == 0

    def changed(self, a, b):
        return self._git("diff", "--name-only", a, b).stdout.split()

    def last_change_time(self, frontend, sha):
        # Newest commit up to `sha` whose own diff release.yml would count.
        log = self._git("log", "--format=%x00%ct", "--name-only", "-n", "500", sha).stdout
        for chunk in log.split("\x00")[1:]:
            head, _, rest = chunk.partition("\n")
            if touches(frontend, rest.split()):
                return int(head.strip())
        return None


def gh_api(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def release_state(repo, prod_head):
    runs = gh_api(
        f"repos/{repo}/actions/workflows/release.yml/runs?branch=prod&per_page=50"
    ).get("workflow_runs", [])
    ok = next((r for r in runs if r.get("conclusion") == "success"), None)
    latest = runs[0] if runs else {}
    return {
        "sha": ok["head_sha"] if ok else None,
        "run_url": ok["html_url"] if ok else None,
        "prod_head": prod_head,
        "latest_run": {k: latest.get(k) for k in ("head_sha", "status", "conclusion", "html_url")},
    }


def load_index(url, path):
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # The host rejects urllib's default User-Agent with a 403.
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "bootc-installer-freshness"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--index-url", default=INDEX_URL)
    p.add_argument("--index-file", help="read the index from a file instead of the URL")
    p.add_argument("--repo", default="tuna-os/bootc-installer")
    p.add_argument("--git-dir", default=".")
    p.add_argument("--prod-ref", default="origin/prod")
    p.add_argument("--report", help="also write the markdown report here")
    p.add_argument("--json", help="also write the verdicts as JSON here")
    args = p.parse_args(argv)

    try:
        images = parse_index(load_index(args.index_url, args.index_file))
        history = GitHistory(args.git_dir)
        released = release_state(args.repo, history.rev_parse(args.prod_ref))
    except Exception as exc:  # noqa: BLE001 - any failure here means "could not check"
        print(f"freshness check could not run: {exc}", file=sys.stderr)
        return 2

    verdicts = [evaluate(fe, images, released, history) for fe in FRONTENDS]
    report = render(verdicts, released, args.index_url)
    print(report, end="")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "released": released,
                    "stale": [v.frontend for v in verdicts if v.stale],
                    "frontends": {
                        v.frontend: {"stale": v.stale, "reasons": v.reasons, "notes": v.notes}
                        for v in verdicts
                    },
                },
                f,
                indent=2,
            )
    return 1 if any(v.stale for v in verdicts) else 0


if __name__ == "__main__":
    sys.exit(main())
