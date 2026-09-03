"""No `run:` block may interpolate `inputs.*`, `github.event.*`, `github.head_ref`
or `github.ref_name` with `${{ }}`.

A `${{ }}` expression is substituted into the script text *before* bash parses
it, so the shell never sees a variable, only the value spliced in verbatim.
Double quotes around the expression do not help: a value containing `"` closes
the quoted string early and the rest is parsed as shell. The site that brought
this here was not even quoted (tuna-os/tunaOS#2295 called it the highest-risk
one left in the org sweep):

    gh release create ${{ github.ref_name }} \\
        --title "bootc-installer ${{ github.ref_name }}" \\

A tag is a ref name, and a ref name can contain almost anything. Whoever can
push a tag can therefore run shell with `github.token` in that job's scope.

The fix is mechanical and the same everywhere: bind the value to a step-level
`env:` entry and reference the shell variable, quoted, inside `run:`:

    env:
      REF_NAME: ${{ github.ref_name }}
    run: |
      gh release create "$REF_NAME" --title "bootc-installer $REF_NAME"

Scope is deliberate. `matrix.*`, `steps.*.outputs.*`, `secrets.*` and `env.*`
are workflow-controlled; `github.repository`, `github.sha`, `github.run_id`
and friends are shaped by GitHub and cannot carry shell metacharacters. The
four roots rejected here are the ones whose value is chosen by whoever
triggered the run: dispatch inputs, the webhook payload, and the two branch or
tag names.
"""

from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)

# Roots whose value is chosen by whoever triggered the run, not by this repo.
UNTRUSTED = re.compile(
    r"(?<![\w.])(inputs\.|github\.event\.|github\.head_ref\b|github\.ref_name\b)"
)


def untrusted_interpolations(script: str) -> list[str]:
    """Every `${{ }}` body in `script` that reads an untrusted root."""
    return [
        match.group(1).strip()
        for match in EXPRESSION.finditer(script)
        if UNTRUSTED.search(match.group(1))
    ]


def run_blocks(path: pathlib.Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job_name, job in (doc.get("jobs") or {}).items():
        for index, step in enumerate(job.get("steps") or []):
            script = step.get("run")
            if isinstance(script, str):
                label = step.get("name") or step.get("id") or f"step {index}"
                yield job_name, label, script


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_run_block_interpolates_untrusted_context(path: pathlib.Path):
    offenders = [
        f"{job}/{step}: ${{{{ {body} }}}}"
        for job, step, script in run_blocks(path)
        for body in untrusted_interpolations(script)
    ]
    assert not offenders, (
        f"{path.name} splices untrusted context into a shell script; bind it "
        "to a step-level env: entry and reference the shell variable instead:\n  "
        + "\n  ".join(offenders)
    )


def test_there_are_workflows_to_check():
    assert len(WORKFLOWS) >= 5


def test_the_detector_recognises_the_shapes_it_guards():
    assert untrusted_interpolations("gh release create ${{ github.ref_name }}") == [
        "github.ref_name"
    ]
    assert untrusted_interpolations('x "${{ inputs.image }}"') == ["inputs.image"]
    assert untrusted_interpolations('BASE="${{ github.event.pull_request.base.sha }}"') == [
        "github.event.pull_request.base.sha"
    ]
    assert untrusted_interpolations("${{ github.head_ref }}") == ["github.head_ref"]
    # Multi-line expressions are still one expression.
    assert untrusted_interpolations("${{\n  inputs.x\n}}") == ["inputs.x"]


def test_the_detector_leaves_trusted_context_alone():
    trusted = (
        '"${{ matrix.variant.app_id }}" "${{ secrets.TOKEN }}" "${{ steps.vars.outputs.tag }}" '
        '"${{ github.repository }}" "${{ github.run_id }}" "${{ github.sha }}" '
        '"${{ github.ref }}" "${{ env.IMAGE }}" "${{ github.token }}"'
    )
    assert untrusted_interpolations(trusted) == []
    # The shell variable the fix leaves behind is not an expression at all.
    assert untrusted_interpolations('gh release create "$REF_NAME"') == []


def test_a_bound_env_entry_is_the_accepted_form(tmp_path: pathlib.Path):
    """The fix shape passes; the original shape from #2295 fails."""
    good = tmp_path / "good.yml"
    good.write_text(
        "on: push\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: release\n"
        "        env:\n          REF_NAME: ${{ github.ref_name }}\n"
        '        run: gh release create "$REF_NAME"\n'
    )
    bad = tmp_path / "bad.yml"
    bad.write_text(
        "on: push\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: release\n"
        "        run: gh release create ${{ github.ref_name }}\n"
    )
    assert [b for _, _, s in run_blocks(good) for b in untrusted_interpolations(s)] == []
    assert [b for _, _, s in run_blocks(bad) for b in untrusted_interpolations(s)] == [
        "github.ref_name"
    ]
