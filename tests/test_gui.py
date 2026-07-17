"""Tests for recorder.gui — tkinter modal construction and state transitions.

These tests skip the actual tkinter event loop (no ``mainloop()``) and
instead verify widget creation, button states, and action wiring.

Requires an X display.  On headless CI, set up ``Xvfb`` or set the
environment variable ``SKIP_GUI_TESTS=1`` to skip.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from unittest import mock

import pytest

from recorder.audio import AudioRecorder, RecorderState
from recorder.config import AppConfig
from recorder.gui import RecorderApp, _refresh_devices


# Skip all GUI tests if no display or explicitly skipped
_need_gui = pytest.mark.skipif(
    os.environ.get("SKIP_GUI_TESTS") == "1",
    reason="SKIP_GUI_TESTS=1",
)

# Apply to all tests in this file
pytestmark = [_need_gui]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(
        mic_device="test_mic",
        monitor_device="test_monitor",
        language="en",
        model="tiny",
    )


@pytest.fixture
def app(cfg: AppConfig) -> RecorderApp:
    """Create a RecorderApp without starting the event loop."""
    try:
        # Quick probe to see if Tk can connect to a display
        probe = tk.Tk()
        probe.withdraw()
        probe.destroy()
    except tk.TclError:
        pytest.skip("No display available for tkinter tests")

    app = RecorderApp(cfg)
    return app


# ---------------------------------------------------------------------------
# Device refresh helper
# ---------------------------------------------------------------------------


class TestRefreshDevices:
    """Test _refresh_devices helper."""

    def test_returns_default_on_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "recorder.gui.list_devices",
            mock.MagicMock(side_effect=Exception("pactl gone")),
        )
        mics, monitors = _refresh_devices()
        assert len(mics) == 1
        assert len(monitors) == 1
        assert mics[0].name == "default"
        assert monitors[0].name == "default"


# ---------------------------------------------------------------------------
# App construction
# ---------------------------------------------------------------------------


class TestRecorderAppConstruction:
    """Test RecorderApp init and basic properties."""

    def test_root_is_withdrawn(self, app: RecorderApp) -> None:
        # Root window exists but is hidden
        assert app._root is not None
        assert app._root.winfo_exists()

    def test_config_is_stored(self, app: RecorderApp, cfg: AppConfig) -> None:
        assert app._config.mic_device == cfg.mic_device
        assert app._config.language == cfg.language

    def test_recorder_is_idle(self, app: RecorderApp) -> None:
        assert app._recorder.state == RecorderState.IDLE

    def test_hotkey_manager_exists(self, app: RecorderApp) -> None:
        assert app._hotkey is not None


# ---------------------------------------------------------------------------
# Modal build
# ---------------------------------------------------------------------------


class TestModalBuild:
    """Test _build_modal creates all expected widgets."""

    def test_build_modal_creates_toplevel(self, app: RecorderApp) -> None:
        app._build_modal()
        assert app._modal is not None
        assert app._modal_visible is True
        assert isinstance(app._modal, tk.Toplevel)

    def test_build_modal_sets_widgets(self, app: RecorderApp) -> None:
        app._build_modal()
        assert app._mic_var is not None
        assert app._monitor_var is not None
        assert app._lang_var is not None
        assert app._model_var is not None
        assert app._timer_var is not None
        assert app._status_var is not None
        assert app._progress is not None
        assert app._button_frame is not None
        assert app._mic_combo is not None
        assert app._monitor_combo is not None

    def test_show_modal_is_idempotent(self, app: RecorderApp) -> None:
        app._show_modal()
        first_modal = app._modal
        app._show_modal()  # second call
        assert app._modal is first_modal  # same instance


# ---------------------------------------------------------------------------
# Button state transitions
# ---------------------------------------------------------------------------


class TestButtonStates:
    """Test that button updates correctly reflect recorder state."""

    def test_idle_buttons(self, app: RecorderApp) -> None:
        app._build_modal()
        # After build, buttons should be in idle state
        status = app._status_var.get()
        assert "Ready" in status

    def test_recording_buttons(self, app: RecorderApp) -> None:
        app._build_modal()
        app._update_buttons_recording()
        status = app._status_var.get()
        assert "Recording" in status

    def test_paused_buttons(self, app: RecorderApp) -> None:
        app._build_modal()
        app._update_buttons_paused()
        status = app._status_var.get()
        assert "paused" in status.lower()

    def test_stopped_buttons(self, app: RecorderApp) -> None:
        app._build_modal()
        app._update_buttons_stopped(123.4)
        status = app._status_var.get()
        assert "Stopped" in status
        assert "02:03" in status  # 123.4s = 2m 3s

    def test_transcribing_buttons(self, app: RecorderApp) -> None:
        app._build_modal()
        app._update_buttons_transcribing()
        status = app._status_var.get()
        assert "Transcribing" in status

    def test_done_buttons(self, app: RecorderApp) -> None:
        app._build_modal()
        app._update_buttons_done()
        status = app._status_var.get()
        assert "Done" in status

    def test_error_buttons(self, app: RecorderApp) -> None:
        app._build_modal()
        app._update_buttons_error("Test failure")
        status = app._status_var.get()
        assert "Error" in status
        assert "Test failure" in status


# ---------------------------------------------------------------------------
# Action wiring
# ---------------------------------------------------------------------------


class TestActions:
    """Test action methods wire correctly to the recorder."""

    def test_on_record_starts_recorder(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)
        app._recorder.state = RecorderState.IDLE
        app._recorder.elapsed = 0.0

        app._on_record()
        app._recorder.start.assert_called_once_with("test_mic", "test_monitor")

    def test_on_pause(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)
        app._recorder.pause.return_value = None
        app._recorder.elapsed = 5.0

        app._on_pause()
        app._recorder.pause.assert_called_once()

    def test_on_resume(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)
        app._recorder.resume_with_source.return_value = None
        app._recorder.elapsed = 5.0

        app._on_resume()
        app._recorder.resume_with_source.assert_called_once_with("test_mic")

    def test_on_stop(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)
        app._recorder.stop.return_value = Path("/tmp/test.wav")
        app._recorder.elapsed = 10.0

        app._on_stop()
        app._recorder.stop.assert_called_once()
        assert app._mixed_path == Path("/tmp/test.wav")

    def test_on_discard(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)

        app._on_discard()
        app._recorder.discard.assert_called_once()
        assert app._mixed_path is None

    def test_on_transcribe_no_recording(self, app: RecorderApp) -> None:
        app._build_modal()
        app._mixed_path = None
        with mock.patch("tkinter.messagebox.showwarning") as mw:
            app._on_transcribe()
            mw.assert_called_once()

    def test_hide_modal_releases_root(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)
        app._recorder.state = RecorderState.IDLE  # allows hiding
        app._hide_modal()
        assert app._modal_visible is False
        assert app._modal is None

    def test_hide_modal_blocked_during_recording(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)
        app._recorder.state = RecorderState.RECORDING
        app._hide_modal()
        assert app._modal_visible is True  # still visible
        assert app._modal is not None


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------


class TestTimer:
    """Test timer start/stop/tick."""

    def test_start_timer_calls_tick(self, app: RecorderApp) -> None:
        app._build_modal()
        app._recorder = mock.MagicMock(spec=AudioRecorder)
        app._recorder.elapsed = 42.0

        app._start_timer()
        assert app._timer_job is not None
        # Timer should display 42s formatted
        displayed = app._timer_var.get()
        assert "00:00:42" in displayed

    def test_stop_timer_cancels(self, app: RecorderApp) -> None:
        app._build_modal()
        app._start_timer()
        assert app._timer_job is not None
        app._stop_timer()
        assert app._timer_job is None
