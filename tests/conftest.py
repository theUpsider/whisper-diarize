"""Shared test fixtures and helpers."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from recorder.config import AppConfig


# ---------------------------------------------------------------------------
# Prevent pynput from being imported during any test — it requires an X11
# display and causes thread deadlocks during garbage collection.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _block_pynput(monkeypatch) -> None:
    """Replace pynput.keyboard.GlobalHotKeys with a harmless MagicMock."""
    monkeypatch.setattr(
        "pynput.keyboard.GlobalHotKeys",
        mock.MagicMock(return_value=mock.MagicMock()),
        raising=False,
    )


# ---------------------------------------------------------------------------
# Temporary directories
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir() -> Path:
    """A temporary directory that is cleaned up after the test."""
    d = Path(tempfile.mkdtemp(prefix="whisper_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_work_dir(temp_dir: Path) -> Path:
    """A work directory for AudioRecorder."""
    wd = temp_dir / "work"
    wd.mkdir()
    return wd


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_config() -> AppConfig:
    """Return a minimal AppConfig for testing."""
    return AppConfig(
        mic_device="test_mic",
        monitor_device="test_monitor",
        language="en",
        model="tiny",
        output_dir="/tmp/whisper_test_output",
    )


@pytest.fixture
def sample_config_file(temp_dir: Path) -> Path:
    """Write a valid config JSON to a temp file."""
    data = {
        "mic_device": "json_mic",
        "monitor_device": "json_monitor",
        "language": "fr",
        "model": "base",
    }
    cfg = temp_dir / "config.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    return cfg


# ---------------------------------------------------------------------------
# pactl JSON output helpers
# ---------------------------------------------------------------------------


def make_pactl_output(sources: list[dict]) -> str:
    """Build a JSON string matching ``pactl --format=json list sources``."""
    return json.dumps(sources)


def make_source(
    name: str,
    description: str = "",
    monitor_of_sink: str | None = None,
) -> dict:
    """Create a single pactl source dict."""
    return {
        "name": name,
        "description": description or name,
        "monitor_of_sink": monitor_of_sink,
    }


# ---------------------------------------------------------------------------
# Fake ffmpeg helpers
# ---------------------------------------------------------------------------


def fake_ffmpeg_that_succeeds() -> mock.MagicMock:
    """Return a mock subprocess.Popen that acts like a running ffmpeg."""
    proc = mock.MagicMock()
    proc.poll.return_value = None
    proc.wait.return_value = 0
    return proc


def fake_ffmpeg_that_fails() -> mock.MagicMock:
    """Return a mock subprocess.Popen that raises on creation."""
    def _raise(*args, **kwargs):
        raise OSError("ffmpeg not found")
    return mock.MagicMock(side_effect=_raise)


# ---------------------------------------------------------------------------
# Fake subprocess.run helpers (for mix / concat / pactl)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pactl(monkeypatch):
    """Patch subprocess.run to return fake pactl JSON."""

    def _patch(sources: list[dict]):
        output = make_pactl_output(sources)
        proc = mock.MagicMock()
        proc.stdout = output
        proc.stderr = ""
        proc.returncode = 0

        def _fake_run(args, **kwargs):
            if args[:2] == ["pactl", "--format=json"]:
                return proc
            return mock.MagicMock(stdout="", stderr="", returncode=0)

        monkeypatch.setattr("subprocess.run", _fake_run)

    return _patch


@pytest.fixture
def mock_run(monkeypatch):
    """Patch subprocess.run to always succeed."""
    proc = mock.MagicMock()
    proc.stdout = ""
    proc.stderr = ""
    proc.returncode = 0
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: proc)
    return proc
