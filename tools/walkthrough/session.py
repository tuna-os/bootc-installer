"""One headless session for one installer: sway, AT-SPI, the mock daemon.

Nothing here draws a picture. grim copies what the compositor shows, the
compositor shows what the real installer draws, and the installer talks to
`fishermand --mock`, which touches no disk.

The session owns its whole environment (HOME, the XDG directories, locale,
time zone, theme), so a picture shows nothing of the machine that made it.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time

from pointer import Pointer

WIDTH, HEIGHT = 1000, 700
HERE = os.path.dirname(os.path.abspath(__file__))


class SessionError(RuntimeError):
    pass


def wait_for(check, timeout, what):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise SessionError(f"timed out: {what}")


class Session:
    def __init__(self, scenario, step_delay="40ms", width=WIDTH, height=HEIGHT,
                 dark=False, fishermand="/out/bin/fishermand", log_dir="/tmp"):
        self.width, self.height, self.dark = width, height, dark
        self.scenario, self.step_delay = scenario, step_delay
        self.fishermand = fishermand
        self.dir = tempfile.mkdtemp(prefix="walk-")
        self.log_dir = log_dir
        self.procs = []
        self.app = None
        self.env = {
            "PATH": f"{HERE}/fixtures/bin:/usr/bin:/usr/sbin:/bin:/sbin",
            "HOME": "/home/liveuser", "USER": "liveuser", "LOGNAME": "liveuser",
            "SHELL": "/bin/bash",
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC",
            "XDG_RUNTIME_DIR": self.dir, "XDG_SESSION_TYPE": "wayland",
            "XDG_SESSION_CLASS": "user", "XDG_DATA_DIRS": "/usr/share",
            "XCURSOR_SIZE": "24",
            "LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe",
            "WLR_BACKENDS": "headless", "WLR_LIBINPUT_NO_DEVICES": "1",
            "WLR_RENDERER": "pixman", "WLR_RENDERER_ALLOW_SOFTWARE": "1",
            "NO_AT_BRIDGE": "0", "GTK_A11Y": "atspi",
            "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1", "ACCESSIBILITY_ENABLED": "1",
        }

    # -- start and stop ----------------------------------------------------

    def _spawn(self, argv, name, env=None, **kw):
        log = open(os.path.join(self.log_dir, f"{name}.log"), "ab")
        p = subprocess.Popen(argv, env=env or self.env, stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, start_new_session=True, **kw)
        self.procs.append((name, p))
        return p

    def start(self):
        os.chmod(self.dir, 0o700)
        if not os.path.exists("/run/.containerenv") and not os.path.exists("/.dockerenv"):
            # The session replaces /etc/os-release and the home directory.
            raise SessionError("run this in the walkthrough container (run.sh)")
        shutil.rmtree("/home/liveuser", ignore_errors=True)
        shutil.copy(os.path.join(HERE, "fixtures/os-release"), "/usr/lib/os-release")
        icons = "/usr/share/icons/hicolor/scalable/apps"
        os.makedirs(icons, exist_ok=True)
        shutil.copy(os.path.join(HERE, "../../data/icons/hicolor/scalable/apps",
                                 "org.bootcinstaller.Installer.svg"), icons)
        for tool in ("gtk4-update-icon-cache", "gtk-update-icon-cache"):
            if shutil.which(tool):
                subprocess.run([tool, "-qtf", "/usr/share/icons/hicolor"],
                               check=False, stderr=subprocess.DEVNULL)
                break
        self._settings()
        os.makedirs("/home/liveuser/.config", exist_ok=True)
        self._system_bus()
        self._mock()
        bus = os.path.join(self.dir, "bus")
        self.env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        self._spawn(["dbus-daemon", "--session", "--nofork", "--nopidfile",
                     f"--address=unix:path={bus}"], "dbus-session")
        wait_for(lambda: os.path.exists(bus), 10, "session bus")
        # No bar, no border: the window is the output, and the output is the
        # picture.
        conf = os.path.join(self.dir, "sway.conf")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write("default_border none\ndefault_floating_border none\n"
                     "hide_edge_borders both\nfocus_follows_mouse no\n"
                     f"output * resolution {self.width}x{self.height} "
                     f"position 0 0 bg #202428 solid_color\n"
                     "seat seat0 fallback true\n")
        self.env["SWAYSOCK"] = os.path.join(self.dir, "sway.sock")
        self._spawn(["sway", "-c", conf], "sway")
        wait_for(lambda: os.path.exists(self.env["SWAYSOCK"]), 20, "sway")
        display = wait_for(lambda: [n for n in os.listdir(self.dir)
                                    if n.startswith("wayland-") and not n.endswith(".lock")],
                           20, "Wayland display")[0]
        self.env["WAYLAND_DISPLAY"] = display
        self.env["XDG_CURRENT_DESKTOP"] = "sway"
        # A keyboard for the whole session: without one the seat has no
        # keyboard focus, and a window then draws itself as inactive.
        self._spawn(["wtype", "-s", "86400000", "-k", "Shift_L"], "keyboard")
        self.pointer = Pointer(self.dir, display, self.width, self.height)
        self.park()
        self._spawn(["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"], "atspi")
        time.sleep(0.5)
        for k, v in (("IsEnabled", "true"), ("ScreenReaderEnabled", "true")):
            subprocess.run(["busctl", "--user", "set-property", "org.a11y.Bus", "/org/a11y/bus",
                            "org.a11y.Status", k, "b", v], env=self.env, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _settings(self):
        """Theme and fonts, the same in each run. No animations: a picture
        must not depend on where an animation is."""
        theme = "prefer-dark" if self.dark else "prefer-light"
        for version in ("gtk-3.0", "gtk-4.0"):
            d = f"/home/liveuser/.config/{version}"
            os.makedirs(d, exist_ok=True)
            with open(f"{d}/settings.ini", "w", encoding="utf-8") as fh:
                fh.write("[Settings]\ngtk-enable-animations=0\n"
                         "gtk-font-name=Adwaita Sans 11\ngtk-cursor-blink=0\n"
                         f"gtk-application-prefer-dark-theme={int(self.dark)}\n")
        with open("/home/liveuser/.config/kdeglobals", "w", encoding="utf-8") as fh:
            scheme = "BreezeDark" if self.dark else "BreezeLight"
            fh.write(f"[General]\nColorScheme={scheme}\nfont=Noto Sans,10\n"
                     "[KDE]\nAnimationDurationFactor=0\n[Icons]\nTheme="
                     f"{'breeze-dark' if self.dark else 'breeze'}\n")
        cosmic = "/home/liveuser/.config/cosmic/com.system76.CosmicTheme.Mode/v1"
        os.makedirs(cosmic, exist_ok=True)
        with open(f"{cosmic}/is_dark", "w", encoding="utf-8") as fh:
            fh.write("true" if self.dark else "false")
        self.env["GSETTINGS_BACKEND"] = "memory"
        override = "/usr/share/glib-2.0/schemas/90_walk.gschema.override"
        with open(override, "w", encoding="utf-8") as fh:
            fh.write("[org.gnome.desktop.interface]\nenable-animations=false\n"
                     f"cursor-blink=false\ncolor-scheme='{theme}'\n"
                     "font-name='Adwaita Sans 11'\n")
        subprocess.run(["glib-compile-schemas", "/usr/share/glib-2.0/schemas"], check=False,
                       stderr=subprocess.DEVNULL)

    def _system_bus(self):
        os.makedirs("/run/dbus", exist_ok=True)
        if os.path.exists("/run/dbus/system_bus_socket"):
            return
        shutil.copy(os.path.join(HERE, "fixtures/system.conf"), "/etc/dbus-1/system.d/walk.conf")
        subprocess.run(["dbus-daemon", "--system", "--fork"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(["python3", os.path.join(HERE, "fixtures/locale1.py")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def _mock(self):
        os.makedirs("/run/systemd", exist_ok=True)
        os.makedirs("/run/fisherman", exist_ok=True)
        self._spawn([self.fishermand, "--mock", "--scenario", self.scenario,
                     "--step-delay", self.step_delay], "fishermand")
        wait_for(lambda: os.path.exists("/run/fisherman/io.tunaos.Fisherman"), 10, "fishermand")

    def launch(self, argv, env, cwd=None):
        full = dict(self.env, **env)
        # The clock of the installer starts at a fixed time, so a date in a
        # picture (a log name, a time stamp) is the same in each run.
        faketime = "/usr/lib64/libfaketimeMT.so.1"
        # Not for Quickshell: it hangs at start with libfaketime (measured).
        if os.path.exists(faketime) and not argv[0].endswith("quickshell"):
            full.update(LD_PRELOAD=faketime, FAKETIME="@2026-01-05 09:00:00",
                        FAKETIME_DONT_RESET="1", FAKETIME_DONT_FAKE_MONOTONIC="1")
        self.app = self._spawn(argv, "app", env=full, cwd=cwd)
        self.app_env = full
        wait_for(lambda: self.windows() or self.app.poll() is not None, 60, "window")
        if self.app.poll() is not None:
            raise SessionError(f"the installer ended with {self.app.returncode}")

    def stop(self):
        for _name, p in reversed(self.procs):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                    p.wait(5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        for path in ("/run/systemd/io.systemd.SysInstall", "/run/systemd/io.systemd.CryptEnroll",
                     "/run/systemd/io.systemd.Shutdown", "/run/fisherman/io.tunaos.Fisherman"):
            if os.path.exists(path):
                os.unlink(path)
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        try:
            self.start()
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(self, *exc):
        self.stop()

    # -- the compositor ----------------------------------------------------

    def sway(self, *words, json_out=False):
        r = subprocess.run(["swaymsg", "-s", self.env["SWAYSOCK"], *(["-r"] if json_out else []),
                            *words], env=self.env, capture_output=True, text=True, check=False)
        return json.loads(r.stdout) if json_out and r.stdout.strip() else r.stdout

    def windows(self):
        found = []

        def walk(node):
            if node.get("pid"):
                found.append(node)
            for child in node.get("nodes", []) + node.get("floating_nodes", []):
                walk(child)
        tree = self.sway("-t", "get_tree", json_out=True)
        if tree:
            walk(tree)
        return found

    def shot(self, path):
        subprocess.run(["grim", "-l", "9", path], env=self.env, check=True)
        return path

    def still(self, path, quiet=0.6, timeout=8):
        """A picture after the screen stopped changing: two in a row are equal.

        A page with a spinner never stops; the last picture is kept then."""
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            self.shot(path)
            with open(path, "rb") as fh:
                now = fh.read()
            if now == last:
                return True
            last = now
            time.sleep(quiet)
        return False

    def click(self, x, y):
        self.pointer.move(x, y)
        time.sleep(0.15)
        self.pointer.button(True)
        time.sleep(0.08)
        self.pointer.button(False)
        time.sleep(0.25)
        self.park()

    def scroll(self, x, y, steps):
        self.pointer.move(x, y)
        time.sleep(0.1)
        self.pointer.scroll(steps)
        time.sleep(0.4)
        self.park()

    def park(self):
        """The pointer away from the widgets: no hover state in a picture."""
        self.pointer.move(self.width - 1, self.height - 1)

    def keys(self, *names):
        for name in names:
            mods = name.split("+")
            argv = ["wtype"]
            for m in mods[:-1]:
                argv += ["-M", m]
            argv += ["-k", mods[-1]]
            for m in mods[:-1]:
                argv += ["-m", m]
            subprocess.run(argv, env=self.env, check=False)
            time.sleep(0.1)

    def type(self, text):
        subprocess.run(["wtype", "-d", "12", "--", text], env=self.env, check=True)
        time.sleep(0.2)
