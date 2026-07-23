"""Enumerate PulseAudio / PipeWire audio sources via ``pactl``."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioDevice:
    """A PulseAudio source (mic or monitor)."""

    name: str
    description: str
    is_monitor: bool  # True = loopback of a sink (system audio), False = mic


def list_devices() -> list[AudioDevice]:
    """Return all available PulseAudio sources, grouped as mic or monitor.

    Requires ``pactl`` on PATH.  Works with both PulseAudio and PipeWire
    (via pipewire-pulse).
    """
    try:
        proc = subprocess.run(
            ["pactl", "--format=json", "list", "sources"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise SystemExit(
            "pactl not found. Install PulseAudio or PipeWire with pipewire-pulse."
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"pactl failed: {exc.stderr.strip()}") from exc

    try:
        sources = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse pactl output: {exc}") from exc

    devices: list[AudioDevice] = []
    for src in sources:
        name = src.get("name", "")
        desc = src.get("description", name)
        # Detection differs across pactl/pipewire-pulse versions:
        # - old PulseAudio JSON: "monitor_of_sink" is present (non-null)
        # - newer pipewire-pulse: no "monitor_of_sink" key at all; instead
        #   "monitor_source" holds the sink it monitors, and
        #   properties["device.class"] == "monitor"
        props = src.get("properties") or {}
        is_monitor = (
            bool(src.get("monitor_of_sink"))
            or bool(src.get("monitor_source"))
            or props.get("device.class") == "monitor"
            or name.endswith(".monitor")
        )
        if name:
            devices.append(AudioDevice(
                name=name, description=desc, is_monitor=is_monitor))

    return devices


def get_mics(devices: list[AudioDevice] | None = None) -> list[AudioDevice]:
    """Filter device list to microphones only."""
    if devices is None:
        devices = list_devices()
    return [d for d in devices if not d.is_monitor]


def get_monitors(devices: list[AudioDevice] | None = None) -> list[AudioDevice]:
    """Filter device list to monitor (system-audio) sources only."""
    if devices is None:
        devices = list_devices()
    return [d for d in devices if d.is_monitor]
