"""Global hotkey listener for X11 sessions (no-op on Wayland).

Uses ``pynput`` to register a configurable global shortcut that toggles
the recording modal.  Posts toggle events to a ``queue.Queue`` so the
tkinter main thread can poll them safely.
"""

from __future__ import annotations

import logging
import os
import queue
import threading

logger = logging.getLogger(__name__)


def is_wayland() -> bool:
    """Detect whether the current session runs on Wayland."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def is_x11() -> bool:
    """Detect whether the current session runs on X11."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "x11"


class HotkeyManager:
    """Listens for a global hotkey and posts toggle events to a queue.

    On Wayland this is a complete no-op — :meth:`start` and :meth:`stop`
    do nothing, and :meth:`poll` always returns ``False``.
    """

    def __init__(self, hotkey: str = "<ctrl>+<alt>+r") -> None:
        self._hotkey = hotkey
        self._queue: queue.Queue[bool] = queue.Queue()
        self._listener: threading.Thread | None = None
        self._running = False

        if is_wayland():
            logger.info("Wayland detected — global hotkeys disabled")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def hotkey(self) -> str:
        return self._hotkey

    @hotkey.setter
    def hotkey(self, value: str) -> None:
        self._hotkey = value
        if self._running:
            self.stop()
            self.start()

    def start(self) -> None:
        """Begin listening for the global hotkey (X11 only)."""
        if is_wayland():
            return
        if self._running:
            return

        self._running = True
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._listener.start()
        logger.info("Hotkey listener started: %s", self._hotkey)

    def stop(self) -> None:
        """Stop the hotkey listener."""
        self._running = False
        # pynput listener will exit when the thread dies;
        # we push a sentinel to unblock any pending poll()
        self._queue.put(False)
        logger.info("Hotkey listener stopped")

    def poll(self) -> bool:
        """Return ``True`` if the hotkey was pressed since the last poll.

        Non-blocking; returns ``False`` immediately if no event is queued.
        """
        try:
            toggle = self._queue.get_nowait()
            # Drain any additional queued events
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            return toggle
        except queue.Empty:
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _listen(self) -> None:
        try:
            from pynput.keyboard import GlobalHotKeys
        except ImportError:
            logger.error("pynput not installed — hotkeys unavailable")
            return

        def on_toggle() -> None:
            self._queue.put(True)

        try:
            with GlobalHotKeys({self._hotkey: on_toggle}) as listener:
                # Keep thread alive while _running is True;
                # listener.join() blocks, so we poll _running periodically
                while self._running:
                    listener.join(timeout=0.5)
        except Exception:
            logger.exception("Hotkey listener crashed")
