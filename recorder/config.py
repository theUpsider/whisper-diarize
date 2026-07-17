"""JSON configuration for Whisper Recorder.

Stored at ``~/.config/whisper-recorder/config.json`` (XDG config home).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


CONFIG_DIR = Path.home() / ".config" / "whisper-recorder"
CONFIG_PATH = CONFIG_DIR / "config.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "hotkey": "<ctrl>+<alt>+r",
    "mic_device": "default",
    "monitor_device": "default",
    "language": "de",
    "model": "large-v3",
    "compute_type": "float16",
    "batch_size": 8,
    "output_dir": str(Path.home() / "WhisperRecordings"),
    "auto_transcribe": False,
    "min_speakers": None,
    "max_speakers": None,
    "num_speakers": None,
    "diarize": True,
    "auto_open_folder": True,
}


@dataclass
class AppConfig:
    """Application configuration with sensible defaults."""

    hotkey: str = "<ctrl>+<alt>+r"
    mic_device: str = "default"
    monitor_device: str = "default"
    language: str = "de"
    model: str = "large-v3"
    compute_type: str = "float16"
    batch_size: int = 8
    output_dir: str = field(default_factory=lambda: str(
        Path.home() / "WhisperRecordings"))
    auto_transcribe: bool = False
    min_speakers: int | None = None
    max_speakers: int | None = None
    num_speakers: int | None = None
    diarize: bool = True
    auto_open_folder: bool = True

    @property
    def hf_token(self) -> str | None:
        """Read Hugging Face token from environment (never stored in config)."""
        return os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")


def load_config() -> AppConfig:
    """Load config from disk, creating it with defaults on first launch."""
    if not CONFIG_PATH.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AppConfig()

    valid_keys = {f.name for f in AppConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in valid_keys}
    return AppConfig(**filtered)


def save_config(config: AppConfig) -> None:
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
