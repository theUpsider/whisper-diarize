"""Tests for recorder.hotkey — session detection and queue-based hotkey toggle."""

from __future__ import annotations

import os
import queue
from unittest import mock

import pytest

from recorder.hotkey import HotkeyManager, is_wayland, is_x11


# HotkeyManager._listen imports pynput lazily — only run tests that
# trigger _listen when X11 is available.
_requires_x11_display = pytest.mark.skipif(
    os.environ.get("XDG_SESSION_TYPE", "").lower() not in ("x11", ""),
    reason="pynput _listen requires X11 display",
)


class TestSessionDetection:
    """Test X11 / Wayland detection."""

    def test_is_wayland_true(self, monkeypatch) -> None:
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        assert is_wayland() is True
        assert is_x11() is False

    def test_is_x11_true(self, monkeypatch) -> None:
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        assert is_x11() is True
        assert is_wayland() is False

    def test_unknown_session(self, monkeypatch) -> None:
        monkeypatch.setenv("XDG_SESSION_TYPE", "tty")
        assert is_wayland() is False
        assert is_x11() is False

    def test_missing_env(self, monkeypatch) -> None:
        monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
        assert is_wayland() is False
        assert is_x11() is False


class TestHotkeyManager:
    """Test HotkeyManager queue-based hotkey behaviour."""

    def test_initial_poll_returns_false(self) -> None:
        hm = HotkeyManager("<ctrl>+<alt>+r")
        assert hm.poll() is False

    def test_hotkey_property(self) -> None:
        hm = HotkeyManager("<ctrl>+<shift>+h")
        assert hm.hotkey == "<ctrl>+<shift>+h"

    def test_set_hotkey_property(self) -> None:
        hm = HotkeyManager("<ctrl>+<alt>+r")
        hm.hotkey = "<ctrl>+<alt>+t"
        assert hm.hotkey == "<ctrl>+<alt>+t"

    @mock.patch("recorder.hotkey.is_wayland", return_value=True)
    def test_start_stop_wayland_is_noop(self, mock_wayland) -> None:
        hm = HotkeyManager()
        hm.start()  # should not raise
        hm.stop()   # should not raise
        assert hm.poll() is False

    def test_stop_pushes_sentinel(self) -> None:
        hm = HotkeyManager()
        hm.stop()
        # After stop, poll should consume the sentinel and return False
        assert hm.poll() is False

    def test_poll_drains_multiple_events(self) -> None:
        hm = HotkeyManager()
        # Manually push toggle events to the internal queue
        hm._queue.put(True)
        hm._queue.put(True)
        hm._queue.put(True)
        # First poll returns True and drains remaining
        assert hm.poll() is True
        # Subsequent poll returns False
        assert hm.poll() is False

    def test_poll_single_event(self) -> None:
        hm = HotkeyManager()
        hm._queue.put(True)
        assert hm.poll() is True
        assert hm.poll() is False

    @mock.patch("recorder.hotkey.is_wayland", return_value=False)
    @_requires_x11_display
    def test_start_on_x11_sets_running(self, mock_wayland) -> None:
        hm = HotkeyManager()
        assert hm._running is False
        hm.start()
        assert hm._running is True
        hm.stop()

    @mock.patch("recorder.hotkey.is_wayland", return_value=False)
    @_requires_x11_display
    def test_start_idempotent(self, mock_wayland) -> None:
        hm = HotkeyManager()
        hm.start()
        hm.start()  # second call should be no-op
        assert hm._running is True
        hm.stop()

    @_requires_x11_display
    def test_hotkey_setter_restarts_listener(self) -> None:
        hm = HotkeyManager("<ctrl>+<alt>+r")
        hm.start()
        assert hm._running is True
        original_listener = hm._listener
        hm.hotkey = "<ctrl>+<alt>+t"
        # Old listener stopped, new one started
        assert hm._listener is not original_listener
        hm.stop()
