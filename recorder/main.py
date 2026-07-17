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
        "--config",
        action="store_true",
        help="Print the path to the configuration file.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Desktop file
# ---------------------------------------------------------------------------

def _venv_python() -> str:
    """Return the path to the Python interpreter inside the active venv, or sys.executable."""
    return os.environ.get("VIRTUAL_ENV") and os.path.join(
        os.environ["VIRTUAL_ENV"], "bin", "python"
    ) or sys.executable


def install_desktop() -> None:
    """Create or overwrite the .desktop file in ~/.local/share/applications/."""
    DESKTOP_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    python_bin = _venv_python()
    entrypoint = str(PROJECT_ROOT / "recorder" / "main.py")

    content = f"""[Desktop Entry]
Name=Whisper Recorder
Comment=Record microphone + system audio, then transcribe with WhisperX
Exec={python_bin} {entrypoint}
Icon=audio-input-microphone
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Recorder;
StartupWMClass=Whisper Recorder
"""

    dest = DESKTOP_INSTALL_DIR / "whisper-recorder.desktop"
    dest.write_text(content, encoding="utf-8")
    dest.chmod(0o755)
    logger.info("Desktop file installed to %s", dest)

    # Also validate if desktop-file-validate is available
    if shutil.which("desktop-file-validate"):
        import subprocess
        subprocess.run(["desktop-file-validate", str(dest)], check=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()

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
