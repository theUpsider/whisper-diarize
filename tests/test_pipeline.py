"""Tests for recorder.pipeline — TranscriptionRunner background thread."""

from __future__ import annotations

import time
from pathlib import Path
import threading
from unittest import mock

import pytest

from main import TranscriptionConfig
from recorder.pipeline import TranscriptionRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tcfg() -> TranscriptionConfig:
    """Minimal config for testing."""
    return TranscriptionConfig(
        hf_token="test_token",
        model="tiny",
        language="en",
        batch_size=1,
    )


@pytest.fixture
def fake_audio_path(temp_dir: Path) -> Path:
    """Create a dummy WAV file (just a placeholder)."""
    p = temp_dir / "fake.wav"
    p.write_text("not a real wav", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTranscriptionRunner:
    """Test TranscriptionRunner lifecycle and callbacks."""

    def test_initial_state(self, tcfg: TranscriptionConfig) -> None:
        runner = TranscriptionRunner(tcfg)
        assert runner.running is False

    def test_start_launches_thread(self, tcfg: TranscriptionConfig, fake_audio_path: Path, temp_dir: Path) -> None:
        progress_calls: list[tuple] = []
        done_calls: list = []

        runner = TranscriptionRunner(
            config=tcfg,
            progress_callback=lambda s, f: progress_calls.append((s, f)),
            done_callback=lambda r, e: done_calls.append((r, e)),
        )

        # Mock transcribe_and_diarize to return a dummy result
        with mock.patch("recorder.pipeline.transcribe_and_diarize") as mock_trans:
            fake_result = {"segments": [
                {"text": "hello", "speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}]}
            mock_trans.return_value = fake_result

            with mock.patch("recorder.pipeline.render_transcript") as mock_render:
                mock_render.return_value = "hello transcript"

                with mock.patch("recorder.pipeline.write_outputs") as mock_write:
                    mock_write.return_value = (
                        Path("/tmp/t.txt"), Path("/tmp/t.json"))

                    runner.start(fake_audio_path, temp_dir)

                    # Wait for thread to complete
                    start = time.monotonic()
                    while runner.running and (time.monotonic() - start) < 5:
                        time.sleep(0.05)

                    assert not runner.running

                    # Progress callbacks fired
                    assert len(progress_calls) >= 2
                    stages = [s for s, _ in progress_calls]
                    assert "Transcribing" in stages or any(
                        "Transcribing" in s for s in stages)

                    # Done callback fired with result
                    assert len(done_calls) == 1
                    result, error = done_calls[0]
                    assert error is None
                    assert result == fake_result

    def test_cannot_start_twice(self, tcfg: TranscriptionConfig, fake_audio_path: Path, temp_dir: Path) -> None:
        runner = TranscriptionRunner(tcfg)

        # Use a lock/signal to ensure first thread is truly running before second start
        started = threading.Event()

        def _slow_transcribe(*args, **kwargs):
            started.set()
            time.sleep(0.5)
            return {"segments": []}

        with mock.patch("recorder.pipeline.transcribe_and_diarize", _slow_transcribe):
            with mock.patch("recorder.pipeline.render_transcript", return_value=""):
                with mock.patch("recorder.pipeline.write_outputs", return_value=(Path("/t.txt"), Path("/t.json"))):
                    runner.start(fake_audio_path, temp_dir)
                    started.wait(timeout=2)
                    with pytest.raises(RuntimeError, match="already in progress"):
                        runner.start(fake_audio_path, temp_dir)

                    # Wait for thread to finish
                    start = time.monotonic()
                    while runner.running and (time.monotonic() - start) < 5:
                        time.sleep(0.05)

    def test_error_callback(self, tcfg: TranscriptionConfig, fake_audio_path: Path, temp_dir: Path) -> None:
        done_calls: list = []

        runner = TranscriptionRunner(
            config=tcfg,
            done_callback=lambda r, e: done_calls.append((r, e)),
        )

        with mock.patch("recorder.pipeline.transcribe_and_diarize") as mt:
            mt.side_effect = RuntimeError("GPU out of memory")

            runner.start(fake_audio_path, temp_dir)

            start = time.monotonic()
            while runner.running and (time.monotonic() - start) < 5:
                time.sleep(0.05)

            assert len(done_calls) == 1
            result, error = done_calls[0]
            assert result is None
            assert error is not None
            assert "GPU out of memory" in error or "RuntimeError" in error

    def test_cancel_sets_flag(self, tcfg: TranscriptionConfig) -> None:
        runner = TranscriptionRunner(tcfg)
        assert runner._cancelled is False
        runner.cancel()
        assert runner._cancelled is True

    def test_progress_callback_exception_does_not_crash(self, tcfg: TranscriptionConfig, fake_audio_path: Path, temp_dir: Path) -> None:
        """If progress callback raises, the transcription still completes."""

        def _broken_progress(stage: str, fraction: float | None) -> None:
            raise ValueError("callback crash")

        done_calls: list = []

        runner = TranscriptionRunner(
            config=tcfg,
            progress_callback=_broken_progress,
            done_callback=lambda r, e: done_calls.append((r, e)),
        )

        with mock.patch("recorder.pipeline.transcribe_and_diarize") as mt:
            mt.return_value = {"segments": []}
            with mock.patch("recorder.pipeline.render_transcript", return_value=""):
                with mock.patch("recorder.pipeline.write_outputs", return_value=(Path("/t.txt"), Path("/t.json"))):
                    runner.start(fake_audio_path, temp_dir)

                    start = time.monotonic()
                    while runner.running and (time.monotonic() - start) < 5:
                        time.sleep(0.05)

                    assert len(done_calls) == 1
                    _result, error = done_calls[0]
                    assert error is None  # transcription succeeded despite broken callback

    def test_done_callback_exception_is_caught(self, tcfg: TranscriptionConfig, fake_audio_path: Path, temp_dir: Path) -> None:
        """If done callback crashes, it doesn't propagate."""

        def _broken_done(result: object, error: str | None) -> None:
            raise RuntimeError("done crash")

        runner = TranscriptionRunner(
            config=tcfg,
            done_callback=_broken_done,
        )

        with mock.patch("recorder.pipeline.transcribe_and_diarize") as mt:
            mt.return_value = {"segments": []}
            with mock.patch("recorder.pipeline.render_transcript", return_value=""):
                with mock.patch("recorder.pipeline.write_outputs", return_value=(Path("/t.txt"), Path("/t.json"))):
                    # Should not raise
                    runner.start(fake_audio_path, temp_dir)

                    start = time.monotonic()
                    while runner.running and (time.monotonic() - start) < 5:
                        time.sleep(0.05)

                    assert not runner.running
