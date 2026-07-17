"""Whisper Recorder — live dual-source recording + transcription GUI."""

from recorder.config import AppConfig, load_config, save_config
from recorder.devices import AudioDevice, list_devices
from recorder.audio import AudioRecorder
from recorder.hotkey import HotkeyManager, is_wayland, is_x11
from recorder.pipeline import TranscriptionRunner

__all__ = [
    "AppConfig",
    "AudioDevice",
    "AudioRecorder",
    "HotkeyManager",
    "TranscriptionRunner",
    "is_wayland",
    "is_x11",
    "list_devices",
    "load_config",
    "save_config",
]
