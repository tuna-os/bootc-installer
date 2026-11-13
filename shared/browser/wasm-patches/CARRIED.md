# Patches carried in the tuna-os forks

The browser-only COSMIC build (`.github/workflows/wasm-cosmic.yml`) needs
five fixes to libraries. Four of them are carried as commits in tuna-os
forks. `frontends/cosmic/web/cargo-patch.toml` pins each fork by a full
commit SHA. The build does not apply patch files.

## Why they are carried

pop-os closed
[pop-os/libcosmic#1446](https://github.com/pop-os/libcosmic/pull/1446)
with "We are no longer accepting LLM-generated changes", and closed
[pop-os/iced#397](https://github.com/pop-os/iced/pull/397) and
[pop-os/iced#398](https://github.com/pop-os/iced/pull/398) unmerged. In
[#105](https://github.com/tuna-os/bootc-installer/issues/105) the
maintainer decided to carry the fixes in the tuna-os forks and not to send
them upstream again. A person can still send one upstream by hand.

## What is carried where

| Patch | Fork and branch | Pinned commit | Fork commits | PR |
|---|---|---|---|---|
| `01` atomicwrites fallback `imp` | tuna-os/rust-atomicwrites `master` | `7e18cf3045168c9e57368470d9d9dfb582d67d8a` | `5c997fa`, `f912bc9`; `ef1b004` drops dependency upper bounds | tuna-os/rust-atomicwrites#1, tuna-os/rust-atomicwrites#12 |
| `02` cosmic-config `system_path` | tuna-os/libcosmic `master` | `f59dea696d6c15568f936286db081e778c264a57` | `7ccdd7a` | tuna-os/libcosmic#1 |
| `06` iced_wgpu `remove_var` cfg | tuna-os/iced `cosmic-wasm/5fc4372` | `2b79c4675969a42d1d3cc1cf5d87bb6f35bb01f6` | `c5ff63f` (from `5e69e98`, tuna-os/iced#1) | tuna-os/iced#10 |
| `03` iced_winit web API refresh | tuna-os/iced `cosmic-wasm/5fc4372` | `2b79c4675969a42d1d3cc1cf5d87bb6f35bb01f6` | `15e0df5` (from `febc844`, tuna-os/iced#2) | tuna-os/iced#10 |
| `07` libcosmic `webgl` passthrough | none | none | none | none |

- `01`: cosmic-config depends on `jackpot51/rust-atomicwrites`.
  tuna-os/rust-atomicwrites is a fork of `untitaker/rust-atomicwrites`, and
  its version is 0.4.4. `Cargo.lock` has 0.4.2. Thus the job runs
  `cargo update -p atomicwrites` before Cargo uses the patch. The fork
  must put no upper bound on a dependency. `Cargo.lock` has a newer
  tempfile and libc, so with a bound Cargo does not use the patch (it only
  warns "patch ... was not used in the crate graph") and the check fails
  in the jackpot51 crate. tuna-os/rust-atomicwrites#12 removed such
  bounds.
- `03` and `06`: libcosmic has iced as a git submodule. The libcosmic pin
  has iced at `5fc4372`. tuna-os/iced `master` has the two fixes on a newer
  iced (a winit bump and a Scrollable change), and that libcosmic does not
  build against it. Thus `cosmic-wasm/5fc4372` is `5fc4372` with the two
  commits on top.
- `07` is a feature request. It was never sent upstream, by design, and no
  fork has it. It stays here as `07-libcosmic-webgl-feature.patch`. The
  `cargo check` does not need it. A render in Chromium needs it.

## How the pins move

Renovate tracks each pin (`customManagers` in `renovate.json`, datasource
`git-refs`). The libcosmic and rust-atomicwrites pins follow `master`. The
iced pin follows `cosmic-wasm/5fc4372`. Renovate opens one group, "COSMIC
wasm forks", and does not automerge it: the job is advisory and stays
green when the check fails. Before you merge a bump, read the step summary
of the job. It must say `COSMIC wasm check: success`.

To move a pin by hand, change the `rev` of each entry of that fork in
`cargo-patch.toml`, and change the table above.
`tests/unit/test_wasm_cosmic.py` makes sure that each entry of one fork has
the same rev, that this file names each rev, and that Renovate tracks each
pin.

Do not delete or force-push a branch that a pin uses. Cargo fetches the
rev, and GitHub can remove a commit that no branch has.

## How to rebase the forks

- **tuna-os/rust-atomicwrites**: merge `untitaker/rust-atomicwrites`
  `master` into the fork `master` by a pull request. Keep the fallback
  `imp` (the `not(any(unix, windows))` arm in `src/lib.rs`), and add no
  upper bound to a dependency.
- **tuna-os/libcosmic**: merge `pop-os/libcosmic` `master` into the fork
  `master` by a pull request. Keep `7ccdd7a`. Then look at the `iced`
  gitlink. If it did not change, only the libcosmic pin moves.
- **tuna-os/iced**, when the libcosmic `iced` gitlink changes to a new
  commit `N`:
  1. Push `N` from `pop-os/iced` to tuna-os/iced as the branch
     `cosmic-wasm/<first 7 of N>`.
  2. On a new branch from `N`, run `git cherry-pick -x c5ff63f 15e0df5`.
     Fix any conflict, and open a pull request against
     `cosmic-wasm/<first 7 of N>`.
  3. Merge it. Pin the merge commit for every iced crate in
     `cargo-patch.toml`, under both libcosmic sources.
  4. Change `currentValueTemplate` of the iced manager in `renovate.json`
     to the new branch.

  If `N` has the fixes from upstream, remove the iced entries instead.

The iced crates must all come from one place. Two copies of `iced_core` do
not link.

To check a change on your computer, use the commands in
[README.md](README.md#reproducing-the-build).

## When upstream takes a fix

Remove the fork entries of that fix from `cargo-patch.toml`, its row from
this table, and its custom manager from `renovate.json` if no pin uses that
fork.
