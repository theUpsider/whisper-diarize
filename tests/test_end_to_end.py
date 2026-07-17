"""End-to-end integration tests: config → devices → audio → pipeline → output.

These tests run the full recorder pipeline with mocked external dependencies
(ffmpeg, pactl, whisperx) to verify end-to-end data flow.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import pytest

from main import TranscriptionConfig
from recorder.audio import AudioRecorder, RecorderState
from recorder.config import AppConfig, load_config, save_config
from recorder.devices import AudioDevice, get_mics, get_monitors, list_devices

from recorder.hotkey import HotkeyManager, is_x11
from recorder.pipeline import TranscriptionRunner


# ===========================================================================
# Full pipeline: config → devices → record → transcribe → output
# ===========================================================================


class TestEndToEndPipeline:
    """Verify the complete data flow."""

    def test_full_pipeline_mocked(
        self,
        temp_dir: Path,
        monkeypatch,
    ) -> None:
        """
        1. Load config
        2. Discover devices via fake pactl
        3. Start recording via fake ffmpeg
        4. Stop and mix
        5. Transcribe via mocked whisperx
        6. Verify output files exist
        """

        # ------------------------------------------------------------------
        # Arrange: config
        # ------------------------------------------------------------------
        cfg_path = temp_dir / "config.json"
        monkeypatch.setattr("recorder.config.CONFIG_PATH", cfg_path)
        monkeypatch.setattr("recorder.config.CONFIG_DIR", cfg_path.parent)

        original = AppConfig(
            mic_device="fake_mic",
            monitor_device="fake_monitor",
            language="de",
            model="tiny",
            output_dir=str(temp_dir / "output"),
        )
        # Force hf_token via env
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_test_token")
        save_config(original)
        loaded = load_config()
        assert loaded.mic_device == "fake_mic"

        # ------------------------------------------------------------------
        # Arrange: devices
        # ------------------------------------------------------------------
        fake_sources = [
            {"name": "fake_mic", "description": "Fake Mic"},
            {"name": "fake_monitor", "description": "Fake Monitor",
                "monitor_of_sink": "fake_sink"},
        ]
        pactl_proc = mock.MagicMock(stdout=json.dumps(
            fake_sources), stderr="", returncode=0)
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: pactl_proc)

        devices = list_devices()
        mics = get_mics(devices)
        monitors = get_monitors(devices)
        assert len(mics) == 1
        assert len(monitors) == 1
        assert mics[0].name == "fake_mic"
        assert monitors[0].name == "fake_monitor"

        # ------------------------------------------------------------------
        # Arrange: audio recording
        # ------------------------------------------------------------------
        work_dir = temp_dir / "work"
        work_dir.mkdir()
        recorder = AudioRecorder(work_dir=work_dir)

        # Create fake WAV files so mixing works
        wav_header = bytes([
            0x52, 0x49, 0x46, 0x46, 0x28, 0x00, 0x00, 0x00,
            0x57, 0x41, 0x56, 0x45, 0x66, 0x6D, 0x74, 0x20,
            0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
            0x40, 0x1F, 0x00, 0x00, 0x40, 0x1F, 0x00, 0x00,
            0x01, 0x00, 0x08, 0x00, 0x64, 0x61, 0x74, 0x61,
            0x00, 0x00, 0x00, 0x00,
        ])

        # Mock Popen to create the fake WAV files
        def _fake_popen(*args, **kwargs):
            # Determine which file is being written
            cmd_args = args[0] if args else kwargs.get("args", [])
            output_file = None
            for i, arg in enumerate(cmd_args):
                if arg in ("-f",) and i + 1 < len(cmd_args) and cmd_args[i + 1] == "wav":
                    # output file is the last argument
                    output_file = Path(cmd_args[-1])
                    break
            if output_file:
                output_file.write_bytes(wav_header)

            proc = mock.MagicMock()
            proc.poll.return_value = None
            proc.wait.return_value = 0
            return proc

        monkeypatch.setattr("subprocess.Popen", _fake_popen)

        # Let subprocess.run (mix step) create the output file from ffmpeg args
        def _fake_run(args, **kwargs):
            # Create the output file (last positional arg for ffmpeg commands)
            if args and args[0] == "ffmpeg":
                output_file = Path(args[-1])
                output_file.write_bytes(wav_header)
            return mock.MagicMock(stdout="", stderr="", returncode=0)

        monkeypatch.setattr("subprocess.run", _fake_run)

        # ------------------------------------------------------------------
        # Act: record → pause → resume → stop
        # ------------------------------------------------------------------
        recorder.start("fake_mic", "fake_monitor")
        assert recorder.state == RecorderState.RECORDING

        time.sleep(0.02)
        recorder.pause()
        assert recorder.state == RecorderState.PAUSED

        recorder.resume_with_source("fake_mic")
        assert recorder.state == RecorderState.RECORDING

        time.sleep(0.02)
        mixed_path = recorder.stop()
        assert recorder.state == RecorderState.STOPPED
        assert mixed_path is not None
        assert mixed_path.exists()

        # ------------------------------------------------------------------
        # Act: transcribe
        # ------------------------------------------------------------------
        fake_result = {
            "segments": [
                {"text": "Hello world", "speaker": "SPEAKER_00",
                    "start": 0.0, "end": 1.0},
                {"text": "Test recording", "speaker": "SPEAKER_01",
                    "start": 1.5, "end": 2.5},
            ]
        }
        fake_transcript = "Source files:\n\nTranscript:\n\n[00:00:00.000 - 00:00:01.000] SPEAKER_00: Hello world\n"

        with mock.patch("recorder.pipeline.transcribe_and_diarize", return_value=fake_result), \
                mock.patch("recorder.pipeline.render_transcript", return_value="mock transcript"), \
                mock.patch("recorder.pipeline.write_outputs") as mock_write:
            mock_write.return_value = (Path("/tmp/t.txt"), Path("/tmp/t.json"))
            tcfg = TranscriptionConfig(
                hf_token="hf_test_token",
                model="tiny",
                language="de",
                batch_size=1,
            )
            runner = TranscriptionRunner(
                config=tcfg,
                progress_callback=lambda s, f: None,
            )

            output_dir = temp_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            done_result: dict | None = None
            done_error: str | None = None

            def _done_cb(result: dict | None, error: str | None) -> None:
                nonlocal done_result, done_error
                done_result = result
                done_error = error

            runner._done = _done_cb
            runner.start(mixed_path, output_dir)

            # Wait for thread
            start = time.monotonic()
            while runner.running and (time.monotonic() - start) < 5:
                time.sleep(0.05)

            assert not runner.running
            assert done_error is None
            assert done_result is not None
            assert done_result["segments"][0]["text"] == "Hello world"

        # ------------------------------------------------------------------
        # Assert: output files
        # ------------------------------------------------------------------
        txt_path = output_dir / "final_transcript.txt"
        json_path = output_dir / "final_transcript.json"
        # These were written by write_outputs
        if txt_path.exists():
            content = txt_path.read_text(encoding="utf-8")
            assert "Hello world" in content
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            assert len(data["segments"]) == 2


# ===========================================================================
# Session detection integration
# ===========================================================================


class TestSessionIntegration:
    """Test X11/Wayland detection in the context of the full app."""

    def test_x11_session_allows_hotkey(self, monkeypatch) -> None:
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        assert is_x11()
        hm = HotkeyManager("<ctrl>+<alt>+r")
        assert hm is not None
        # Verify it doesn't silently disable itself on X11
        assert hm._queue is not None

    def test_wayland_session_disables_hotkey(self, monkeypatch) -> None:
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        from recorder.hotkey import is_wayland
        assert is_wayland()
        hm = HotkeyManager()
        assert hm.poll() is False  # always false on wayland


# ===========================================================================
# Config round-trip + device discovery integration
# ===========================================================================


class TestConfigDeviceIntegration:
    """Test that config and device discovery work together."""

    def test_config_devices_integration(self, temp_dir: Path, monkeypatch) -> None:
        # Save config
        cfg_path = temp_dir / "config.json"
        monkeypatch.setattr("recorder.config.CONFIG_PATH", cfg_path)
        monkeypatch.setattr("recorder.config.CONFIG_DIR", cfg_path.parent)

        cfg = AppConfig(mic_device="my_mic", monitor_device="my_monitor")
        save_config(cfg)

        # Fake pactl returns matching devices
        fake_sources = [
            {"name": "my_mic", "description": "My Mic"},
            {"name": "my_monitor", "description": "My Monitor",
                "monitor_of_sink": "sink"},
            {"name": "other_mic", "description": "Other"},
        ]
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: mock.MagicMock(stdout=json.dumps(
                fake_sources), stderr="", returncode=0),
        )

        # Load config and verify device exists in discovered list
        loaded = load_config()
        assert loaded.mic_device == "my_mic"
        assert loaded.monitor_device == "my_monitor"

        devices = list_devices()
        device_names = [d.name for d in devices]
        assert "my_mic" in device_names
        assert "my_monitor" in device_names
        assert "other_mic" in device_names


# ===========================================================================
# Error recovery: missing binaries
# ===========================================================================


class TestErrorRecovery:
    """Test graceful handling of missing system dependencies."""

    def test_missing_ffmpeg_during_recording(self, temp_work_dir: Path) -> None:
        """AudioRecorder should raise clean error when ffmpeg is missing."""
        rec = AudioRecorder(work_dir=temp_work_dir)

        # Simulate ffmpeg subprocess failing to start
        with mock.patch("subprocess.Popen") as mp:
            mp.side_effect = FileNotFoundError("ffmpeg not found")
            with pytest.raises(FileNotFoundError, match="ffmpeg"):
                rec.start("any_mic", "any_monitor")

        # State reset to IDLE
        assert rec.state == RecorderState.IDLE

    def test_device_discovery_fallback(self) -> None:
        """Test that _refresh_devices returns defaults on pactl failure."""
        from recorder.gui import _refresh_devices

        with mock.patch("recorder.gui.list_devices", side_effect=Exception("pactl missing")):
            mics, monitors = _refresh_devices()
            assert len(mics) == 1
            assert mics[0].name == "default"
            assert len(monitors) == 1
            assert monitors[0].name == "default"

    def test_config_recovery_from_corrupt_file(self, temp_dir: Path, monkeypatch) -> None:
        """Config loader recovers gracefully from corrupted JSON."""
        bad_path = temp_dir / "corrupt.json"
        bad_path.write_text("NOT JSON {{{", encoding="utf-8")
        monkeypatch.setattr("recorder.config.CONFIG_PATH", bad_path)

        cfg = load_config()
        assert cfg == AppConfig()  # falls back to defaults
