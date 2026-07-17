"""Tests for recorder.devices."""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from recorder.devices import (
    AudioDevice,
    get_mics,
    get_monitors,
    list_devices,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pactl_fail_stderr() -> str:
    return "Failure: No such entity"


# ---------------------------------------------------------------------------
# AudioDevice
# ---------------------------------------------------------------------------


class TestAudioDevice:
    def test_mic_device(self) -> None:
        d = AudioDevice(
            name="alsa_input.usb",
            description="Yeti Microphone",
            is_monitor=False,
        )
        assert d.name == "alsa_input.usb"
        assert d.description == "Yeti Microphone"
        assert d.is_monitor is False

    def test_monitor_device(self) -> None:
        d = AudioDevice(
            name="alsa_output.pci.monitor",
            description="Monitor of Built-in Audio",
            is_monitor=True,
        )
        assert d.is_monitor is True

    def test_equality(self) -> None:
        a = AudioDevice("x", "d", False)
        b = AudioDevice("x", "d", False)
        assert a == b  # dataclass equality

    def test_immutable(self) -> None:
        d = AudioDevice("x", "d", False)
        with pytest.raises(Exception):
            d.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------


class TestListDevices:
    def test_parses_mic_and_monitor(self, monkeypatch) -> None:
        output = json.dumps([
            {
                "name": "alsa_input.usb",
                "description": "USB Mic",
            },
            {
                "name": "alsa_output.pci.monitor",
                "description": "Built-in Monitor",
                "monitor_of_sink": "alsa_output.pci.analog-stereo",
            },
        ])

        def _fake_run(*args, **kwargs):
            return mock.MagicMock(stdout=output, stderr="", returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        devices = list_devices()
        assert len(devices) == 2
        mics = [d for d in devices if not d.is_monitor]
        monitors = [d for d in devices if d.is_monitor]
        assert len(mics) == 1
        assert len(monitors) == 1
        assert mics[0].name == "alsa_input.usb"
        assert monitors[0].name == "alsa_output.pci.monitor"

    def test_empty_list(self, monkeypatch) -> None:
        def _fake_run(*args, **kwargs):
            return mock.MagicMock(stdout="[]", stderr="", returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        devices = list_devices()
        assert devices == []

    def test_missing_name_skipped(self, monkeypatch) -> None:
        output = json.dumps([
            {"description": "no name here"},
            {"name": "good_one", "description": "Good"},
        ])

        def _fake_run(*args, **kwargs):
            return mock.MagicMock(stdout=output, stderr="", returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        devices = list_devices()
        assert len(devices) == 1
        assert devices[0].name == "good_one"

    def test_pactl_not_installed(self, monkeypatch) -> None:
        def _fake_run(*args, **kwargs):
            raise FileNotFoundError("pactl not found")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        with pytest.raises(SystemExit, match="pactl not found"):
            list_devices()

    def test_pactl_failure(self, monkeypatch) -> None:
        def _fake_run(*args, **kwargs):
            raise subprocess.CalledProcessError(
                1, "pactl", stderr=_pactl_fail_stderr()
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        with pytest.raises(SystemExit, match="pactl failed"):
            list_devices()

    def test_invalid_json(self, monkeypatch) -> None:
        def _fake_run(*args, **kwargs):
            return mock.MagicMock(stdout="{not json", stderr="", returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        with pytest.raises(SystemExit, match="Failed to parse pactl"):
            list_devices()


# ---------------------------------------------------------------------------
# get_mics / get_monitors
# ---------------------------------------------------------------------------


class TestFilters:
    def test_get_mics(self) -> None:
        devices = [
            AudioDevice("a", "mic a", False),
            AudioDevice("b", "mon b", True),
            AudioDevice("c", "mic c", False),
        ]
        mics = get_mics(devices)
        assert len(mics) == 2
        assert all(not d.is_monitor for d in mics)

    def test_get_monitors(self) -> None:
        devices = [
            AudioDevice("a", "mic a", False),
            AudioDevice("b", "mon b", True),
        ]
        monitors = get_monitors(devices)
        assert len(monitors) == 1
        assert monitors[0].name == "b"

    def test_get_mics_with_none_calls_list_devices(self, monkeypatch) -> None:
        output = json.dumps([
            {"name": "only_mic", "description": "Mic"},
        ])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: mock.MagicMock(stdout=output,
                                            stderr="", returncode=0),
        )
        mics = get_mics()
        assert len(mics) == 1
        assert mics[0].name == "only_mic"

    def test_get_monitors_with_none_calls_list_devices(self, monkeypatch) -> None:
        output = json.dumps([
            {"name": "mon", "monitor_of_sink": "sink1", "description": "Mon"},
        ])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: mock.MagicMock(stdout=output,
                                            stderr="", returncode=0),
        )
        monitors = get_monitors()
        assert len(monitors) == 1
        assert monitors[0].name == "mon"
