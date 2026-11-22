# Varlink client examples

Thin Varlink clients for the installer daemon (tuna-os/fisherman#512).
Varlink is JSON over a UNIX socket, so each client is under 150 lines. Issue:
tuna-os/bootc-installer#442.

## The wire format

- A message is one JSON object, then a NUL byte (0x00).
- A call is `{"method": "<interface>.<Method>", "parameters": {...}}`.
- Add `"more": true` for a stream of replies. Every reply but the last has
  `"continues": true`. The last reply can have empty parameters.
- An error reply is `{"error": "<interface>.<Name>", "parameters": {...}}`.
  It ends the call.
- One connection carries one call at a time. Open a second connection to
  cancel an install that is in progress.

Passphrases and recovery keys pass through `parameters`. No client logs a
request or a reply. The error type of each client shows the error name only.

## Clients

| Language | Path | Dependencies | Status |
|---|---|---|---|
| Python | `python/` | stdlib only | tested |
| Go | `go/` | stdlib only | tested |
| Qt 6 C++ | `cpp/` | QtCore, QtNetwork | tested with Qt 6.4.2 |
| Rust | `rust/` | `serde_json` | tested with Cargo 1.99 |

"Tested" means that the unit tests of this directory pass. They run each
client against a scripted peer on a UNIX socket. The peer tests the wire
format. It is not the mock daemon of tuna-os/fisherman. Nothing here has run
against `fishermand`, which does not exist yet.

The Python client also ran
against a real systemd service: `GetInfo` and an error reply on
`systemd-resolved`. No client has read a stream of many replies from a real
service.

The C++ header is a recipe, not a library. It has no moc step. The Rust crate
and the Go module are examples that a frontend copies or vendors. Issue 512 does not name the socket path of `io.tunaos.Fisherman` (see `shared/flow/README.md`), so each client takes a path.

## Sizes

A toolkit writes a size with a no-break space (U+00A0, from GLib) or a narrow
no-break space (U+202F). A test that compares `500.1 GB` with that text fails
on a character that nobody sees (projectbluefin/utah#1437). Each client has
`normalize_size_text` and `parse_size`. `fixtures/sizes.json` holds the cases,
and all four implementations read that file.

## Run the tests

```bash
python3 -m pytest tests/unit/test_shared_client.py
(cd shared/client/go && go test ./...)
(cd shared/client/rust && cargo test)
```

For the Qt recipe:

```bash
Q=/usr/include/x86_64-linux-gnu/qt6
g++ -std=c++17 -fPIC -I$Q -I$Q/QtCore -I$Q/QtNetwork \
  shared/client/cpp/test_varlink.cpp -o /tmp/test_varlink -lQt6Core -lQt6Network
/tmp/test_varlink shared/client/fixtures/sizes.json
```

The include paths are those of Debian and Ubuntu. A CMake file is not here,
because no one tested one.

## Examples

Python, Go and Rust have an example that lists the disks of
`io.systemd.SysInstall`, as gnome-setup does. The Go and Rust examples
compile. Nobody ran any of them against
a service that offers `ListCandidateDevices`. The C++ recipe has tests only.
