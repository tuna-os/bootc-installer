"""How to start each installer, as its package starts it."""

import glob
import os
import subprocess

SRC = os.environ.get("WALK_SRC", "/src")
OUT = os.environ.get("WALK_OUT", "/out")
TUNAOS = os.environ.get("WALK_TUNAOS", "/pins/tunaos")
BRANDING = os.path.join(SRC, "shared/walkthrough/capture-branding.json")


def icd():
    found = sorted(glob.glob("/usr/share/vulkan/icd.d/lvp_icd*.json"))
    return found[0] if found else ""


COMMON = {
    "TUNA_INSTALLER_BACKEND": "daemon",
    "BOOTC_INSTALLER_BRANDING": BRANDING,
    "BOOTC_INSTALLER_PRODUCT_NAME": "TunaOS",
    "TUNA_EULA_FILE": "/nonexistent/eula.xml",
    # The image list of the capture: no product of ours (shared/walkthrough).
    "FISHERMAN_IMAGES_PATH": os.path.join(SRC, "shared/walkthrough/capture-catalog.json"),
}


def command(frontend):
    """(argv, environment) of the installer."""
    if frontend == "kde":
        return [f"{OUT}/kde/tuna-installer-kde"], {
            "QT_QPA_PLATFORM": "wayland", "QT_QUICK_CONTROLS_STYLE": "org.kde.desktop",
            "QT_WAYLAND_DISABLE_WINDOWDECORATION": "1", "QT_QUICK_BACKEND": "software",
            "QT_QPA_PLATFORMTHEME": "kde"}
    if frontend == "niri":
        return ["quickshell", "-p", f"{SRC}/frontends/niri/ui/installer.qml"], {
            "TUNA_BACKEND": f"{OUT}/bin/tuna-installer-backend", "QT_QPA_PLATFORM": "wayland",
            "QT_WAYLAND_DISABLE_WINDOWDECORATION": "1", "QT_QUICK_BACKEND": "software"}
    if frontend == "xfce":
        return ["python3", f"{SRC}/frontends/xfce/tuna-installer-xfce"], {
            "BOOTC_INSTALLER_BACKEND": "daemon",
            "GDK_BACKEND": "wayland", "PYTHONDONTWRITEBYTECODE": "1",
            "GTK_THEME": "Adwaita"}
    if frontend == "cosmic":
        return [os.environ.get("WALK_COSMIC_BIN", f"{OUT}/cosmic/release/tuna-installer-cosmic")], {
            "VK_ICD_FILENAMES": icd(), "WINIT_UNIX_BACKEND": "wayland"}
    if frontend == "gnome":
        # Its data paths are compiled in: install the tree as the medium does.
        if not os.path.exists("/usr/bin/gnome-setup"):
            subprocess.run(["cp", "-a", f"{OUT}/gnome/gnome-setup/.", "/"], check=True)
            subprocess.run(["glib-compile-schemas", "/usr/share/glib-2.0/schemas"], check=False)
            # The page list of the medium. Its post-install unit belongs to
            # systemd on the medium, which the container has not got.
            with open(os.path.join(TUNAOS, "installer-medium/frontends/gnome/pages.conf"),
                      encoding="utf-8") as fh:
                conf = [ln for ln in fh if not ln.startswith("post-install-unit=")]
            with open("/usr/lib/gnome-setup/pages.conf", "w", encoding="utf-8") as fh:
                fh.writelines(conf)
            os.makedirs("/run/tunaos", exist_ok=True)
            open("/run/tunaos/live", "w").close()
        return ["/usr/bin/gnome-setup"], {
            "GSK_RENDERER": "cairo", "GDK_BACKEND": "wayland",
            "SETUP_OVERRIDE_IN_SESSION": "true"}
    raise SystemExit(f"unknown frontend {frontend}")


def set_terms(frontend, path):
    """gnome-setup reads its terms from a fixed path, not from TUNA_EULA_FILE."""
    if frontend != "gnome":
        return
    target = "/usr/share/gnome-setup/eula.xml"
    if path:
        subprocess.run(["cp", path, target], check=True)
    elif os.path.exists(target):
        os.unlink(target)
