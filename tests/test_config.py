"""Tests for recorder.config."""

from __future__ import annotations

import json
from pathlib import Path

from recorder.config import (
    AppConfig,
    CONFIG_DIR,
    CONFIG_PATH,
    DEFAULT_CONFIG,
    load_config,
    save_config,
)


class TestAppConfig:
    """Unit tests for AppConfig dataclass."""

    def test_defaults(self) -> None:
        cfg = AppConfig()
        assert cfg.hotkey == "<ctrl>+<alt>+r"
        assert cfg.mic_device == "default"
        assert cfg.monitor_device == "default"
        assert cfg.language == "de"
        assert cfg.model == "large-v3"
        assert cfg.compute_type == "float16"
        assert cfg.batch_size == 8
        assert cfg.auto_transcribe is False
        assert cfg.min_speakers is None
        assert cfg.max_speakers is None
        assert cfg.num_speakers is None
        assert cfg.diarize is True

    def test_hf_token_reads_env(self, monkeypatch) -> None:
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_abc123")
        cfg = AppConfig()
        assert cfg.hf_token == "hf_abc123"

    def test_hf_token_fallback(self, monkeypatch) -> None:
        monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
        monkeypatch.delenv("HF_TOKEN", raising=False)
        cfg = AppConfig()
        assert cfg.hf_token is None

    def test_hf_token_is_not_stored_in_config(self) -> None:
        """hf_token must never appear in the asdict/serialized form."""
        data = AppConfig.__dataclass_fields__
        assert "hf_token" not in data, "hf_token is a property, not a field"

    def test_output_dir_default(self) -> None:
        cfg = AppConfig()
        assert "WhisperRecordings" in cfg.output_dir

    def test_custom_values(self) -> None:
        cfg = AppConfig(
            mic_device="alsa_input.usb",
            monitor_device="alsa_output.pci.monitor",
            language="en",
            model="turbo",
            num_speakers=2,
        )
        assert cfg.mic_device == "alsa_input.usb"
        assert cfg.monitor_device == "alsa_output.pci.monitor"
        assert cfg.language == "en"
        assert cfg.model == "turbo"
        assert cfg.num_speakers == 2


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_defaults_when_no_file(self, temp_dir: Path, monkeypatch) -> None:
        nonexistent = temp_dir / "nonexistent.json"
        monkeypatch.setattr("recorder.config.CONFIG_PATH", nonexistent)
        cfg = load_config()
        assert cfg == AppConfig()

    def test_load_partial_json(self, sample_config_file: Path, monkeypatch) -> None:
        monkeypatch.setattr("recorder.config.CONFIG_PATH", sample_config_file)
        cfg = load_config()
        assert cfg.mic_device == "json_mic"
        assert cfg.monitor_device == "json_monitor"
        assert cfg.language == "fr"
        assert cfg.model == "base"
        # Unspecified keys fall back to defaults
        assert cfg.hotkey == AppConfig().hotkey
        assert cfg.batch_size == AppConfig().batch_size

    def test_load_invalid_json(self, temp_dir: Path, monkeypatch) -> None:
        bad = temp_dir / "bad.json"
        bad.write_text("{invalid", encoding="utf-8")
        monkeypatch.setattr("recorder.config.CONFIG_PATH", bad)
        cfg = load_config()
        assert cfg == AppConfig()

    def test_load_ignores_unknown_keys(self, temp_dir: Path, monkeypatch) -> None:
        cfg_file = temp_dir / "extra.json"
        cfg_file.write_text(
            json.dumps({"mic_device": "test", "made_up_key": 999}), encoding="utf-8"
        )
        monkeypatch.setattr("recorder.config.CONFIG_PATH", cfg_file)
        cfg = load_config()
        assert cfg.mic_device == "test"
        # made_up_key is silently dropped


class TestSaveConfig:
    """Tests for save_config()."""

    def test_save_creates_directory(self, temp_dir: Path, monkeypatch) -> None:
        cfg_path = temp_dir / ".config" / "whisper-recorder" / "config.json"
        monkeypatch.setattr("recorder.config.CONFIG_PATH", cfg_path)
        monkeypatch.setattr("recorder.config.CONFIG_DIR", cfg_path.parent)
        cfg = AppConfig(mic_device="saved_mic")
        save_config(cfg)
        assert cfg_path.exists()

    def test_save_and_reload_roundtrip(self, temp_dir: Path, monkeypatch) -> None:
        cfg_path = temp_dir / "roundtrip.json"
        monkeypatch.setattr("recorder.config.CONFIG_PATH", cfg_path)
        original = AppConfig(
            mic_device="rt_mic",
            language="es",
            model="medium",
            batch_size=4,
        )
        save_config(original)
        reloaded = load_config()
        assert reloaded.mic_device == "rt_mic"
        assert reloaded.language == "es"
        assert reloaded.model == "medium"
        assert reloaded.batch_size == 4
        # Defaults for unset fields
        assert reloaded.hotkey == AppConfig().hotkey
        assert reloaded.compute_type == AppConfig().compute_type


class TestDefaultConfig:
    """Sanity checks on the DEFAULT_CONFIG dict."""

    def test_default_config_keys_match_dataclass(self) -> None:
        field_names = {f.name for f in AppConfig.__dataclass_fields__.values()}
        default_keys = set(DEFAULT_CONFIG.keys())
        assert default_keys == field_names
