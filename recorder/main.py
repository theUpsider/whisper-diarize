"""Entry point for the Whisper Recorder GUI.

Usage::

    python -m recorder.main              # launch the GUI
    python -m recorder.main --install-desktop  # install .desktop file

Configuration lives at ``~/.config/whisper-recorder/config.json``.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from recorder.config import load_config
from recorder.gui import RecorderApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("recorder.main")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_TEMPLATE = PROJECT_ROOT / "assets" / "whisper-recorder.desktop"
DESKTOP_INSTALL_DIR = Path.home() / ".local" / "share" / "applications"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Whisper Recorder — live recording + transcription GUI",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="Install the .desktop file so the app appears in your launcher.",
    )
    parser.add_argument(
        "--uninstall-desktop",
        action="store_true",
        help="Remove the installed .desktop file.",
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Print the path to the configuration file.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Desktop file
# ---------------------------------------------------------------------------

def _resolve_entrypoint() -> str:
    """Return the path to the installed ``whisper-recorder`` script.

    Prefers the venv bin directory (next to sys.executable), falls back to
    finding the script via ``shutil.which``, and finally returns
    ``sys.executable`` so the desktop file is at least launchable.
    """
    venv_bin = Path(sys.executable).parent
    entry = venv_bin / "whisper-recorder"
    if entry.exists():
        return str(entry)
    found = shutil.which("whisper-recorder")
    if found:
        return found
    return sys.executable


def _refresh_desktop_database() -> None:
    """Ask the desktop environment to refresh its cached application list.

    KDE/XFCE menus can keep showing a stale entry (old Exec path) until this
    runs; GNOME picks up changes on its own but running it is harmless.
    """
    if shutil.which("update-desktop-database"):
        import subprocess
        subprocess.run(
            ["update-desktop-database", str(DESKTOP_INSTALL_DIR)],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install_desktop() -> None:
    """Install the .desktop file to ~/.local/share/applications/, replacing any prior install."""
    DESKTOP_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    if not DESKTOP_TEMPLATE.exists():
        logger.error("Desktop template not found: %s", DESKTOP_TEMPLATE)
        return

    dest = DESKTOP_INSTALL_DIR / "whisper-recorder.desktop"
    if dest.exists():
        dest.unlink()

    entrypoint = _resolve_entrypoint()
    content = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
    content = content.replace("WHISPER_RECORDER_BIN", entrypoint)

    dest.write_text(content, encoding="utf-8")
    dest.chmod(0o755)
    logger.info("Desktop file installed to %s", dest)

    # Also validate if desktop-file-validate is available
    if shutil.which("desktop-file-validate"):
        import subprocess
        subprocess.run(["desktop-file-validate", str(dest)], check=False)

    _refresh_desktop_database()


def uninstall_desktop() -> None:
    """Remove the installed .desktop file, if present."""
    dest = DESKTOP_INSTALL_DIR / "whisper-recorder.desktop"
    if dest.exists():
        dest.unlink()
        logger.info("Desktop file removed: %s", dest)
    else:
        logger.info("No desktop file installed at %s", dest)
    _refresh_desktop_database()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()

    if args.uninstall_desktop:
        uninstall_desktop()
        print(
            f"Desktop file removed from {DESKTOP_INSTALL_DIR / 'whisper-recorder.desktop'}")
        return 0

    if args.install_desktop:
        install_desktop()
        print(
            f"Desktop file installed to {DESKTOP_INSTALL_DIR / 'whisper-recorder.desktop'}")
        return 0

    if args.config:
        from recorder.config import CONFIG_PATH
        print(str(CONFIG_PATH))
        return 0

    # Launch the GUI
    cfg = load_config()
    app = RecorderApp(cfg)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
