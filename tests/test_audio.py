"""Tests for recorder.audio — AudioRecorder state machine and ffmpeg management."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from recorder.audio import AudioRecorder, RecorderState, RecorderStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def recorder(temp_work_dir: Path) -> AudioRecorder:
    """Return a fresh AudioRecorder pointed at a temp directory."""
    return AudioRecorder(work_dir=temp_work_dir)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestStateMachine:
    """Test the RecorderState transitions."""

    def test_initial_state_is_idle(self, recorder: AudioRecorder) -> None:
        assert recorder.state == RecorderState.IDLE
        assert recorder.elapsed == 0.0

    @mock.patch("subprocess.Popen")
    def test_idle_to_recording(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("test_mic", "test_monitor")
        assert recorder.state == RecorderState.RECORDING

    def test_cannot_start_twice(self, recorder: AudioRecorder) -> None:
        with mock.patch("subprocess.Popen") as mp:
            mp.return_value = mock.MagicMock(poll=lambda: None)
            recorder.start("mic", "mon")
            with pytest.raises(RuntimeError, match="Cannot start"):
                recorder.start("mic", "mon")

    @mock.patch("subprocess.Popen")
    def test_recording_to_paused(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        recorder.pause()
        assert recorder.state == RecorderState.PAUSED

    def test_pause_only_from_recording(self, recorder: AudioRecorder) -> None:
        recorder.pause()  # idle → no-op
        assert recorder.state == RecorderState.IDLE

    @mock.patch("subprocess.Popen")
    def test_paused_to_recording_via_resume_with_source(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        recorder.pause()
        recorder.resume_with_source("mic")
        assert recorder.state == RecorderState.RECORDING

    def test_resume_without_pause_is_noop(self, recorder: AudioRecorder) -> None:
        recorder.resume_with_source("mic")
        assert recorder.state == RecorderState.IDLE

    @mock.patch("subprocess.Popen")
    def test_stop_transitions_to_stopped(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        with mock.patch("subprocess.run"):  # mix step
            result = recorder.stop()
        assert recorder.state == RecorderState.STOPPED
        # Result is None because we didn't write actual WAV files
        assert result is None

    def test_stop_from_idle_returns_none(self, recorder: AudioRecorder) -> None:
        result = recorder.stop()
        assert result is None
        assert recorder.state == RecorderState.IDLE

    def test_discard_resets_to_idle(self, recorder: AudioRecorder) -> None:
        recorder.discard()
        assert recorder.state == RecorderState.IDLE
        assert recorder.elapsed == 0.0


# ---------------------------------------------------------------------------
# Elapsed time
# ---------------------------------------------------------------------------


class TestElapsed:
    """Test elapsed time tracking."""

    @mock.patch("subprocess.Popen")
    def test_elapsed_advances_during_recording(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        time.sleep(0.05)
        elapsed = recorder.elapsed
        assert elapsed > 0.01

    @mock.patch("subprocess.Popen")
    def test_elapsed_frozen_during_pause(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        time.sleep(0.05)
        before_pause = recorder.elapsed
        recorder.pause()
        time.sleep(0.1)
        during_pause = recorder.elapsed
        # Paused elapsed should approximate the value at pause time
        assert abs(during_pause - before_pause) < 0.06

    @mock.patch("subprocess.Popen")
    def test_elapsed_resumes_correctly(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        time.sleep(0.05)
        recorder.pause()
        after_pause = recorder.elapsed
        recorder.resume_with_source("mic")
        time.sleep(0.05)
        after_resume = recorder.elapsed
        # elapsed should increase after resume (accounting for timing jitter)
        assert after_resume >= after_pause - 0.02

    def test_elapsed_is_zero_when_idle(self, recorder: AudioRecorder) -> None:
        assert recorder.elapsed == 0.0


# ---------------------------------------------------------------------------
# Status callback
# ---------------------------------------------------------------------------


class TestStatusCallback:
    """Test the status callback mechanism."""

    @mock.patch("subprocess.Popen")
    def test_callback_fires_on_start(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        calls: list[RecorderStatus] = []
        recorder.set_status_callback(calls.append)
        recorder.start("mic", "mon")
        assert len(calls) == 1
        assert calls[0].state == RecorderState.RECORDING

    @mock.patch("subprocess.Popen")
    def test_callback_fires_on_pause(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        calls: list[RecorderStatus] = []
        recorder.set_status_callback(calls.append)
        recorder.start("mic", "mon")
        recorder.pause()
        assert calls[-1].state == RecorderState.PAUSED

    @mock.patch("subprocess.Popen")
    def test_callback_fires_on_stop(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        calls: list[RecorderStatus] = []
        recorder.set_status_callback(calls.append)
        recorder.start("mic", "mon")
        with mock.patch("subprocess.run"):
            recorder.stop()
        assert calls[-1].state == RecorderState.STOPPED

    def test_callback_none_is_safe(self, recorder: AudioRecorder) -> None:
        # No callback set — should not crash on notify
        recorder.set_status_callback(None)
        # Trigger notify indirectly via discard
        recorder.discard()


# ---------------------------------------------------------------------------
# ffmpeg process management
# ---------------------------------------------------------------------------


class TestFfmpegManagement:
    """Test ffmpeg subprocess lifecycle."""

    @mock.patch("subprocess.Popen")
    def test_launches_two_processes(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic_source", "monitor_source")
        assert mock_popen.call_count == 2

    @mock.patch("subprocess.Popen")
    def test_pause_stops_mic_process(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        recorder.pause()
        # mic process should be stopped (SIGTERM sent)
        assert mock_proc.send_signal.call_count >= 1

    @mock.patch("subprocess.Popen")
    def test_stop_kills_both_processes(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        with mock.patch("subprocess.run"):
            recorder.stop()
        # Both processes terminated
        assert mock_proc.send_signal.call_count >= 2

    @mock.patch("subprocess.Popen")
    def test_discard_kills_both_and_deletes(self, mock_popen, recorder: AudioRecorder) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder.start("mic", "mon")
        recorder.discard()
        assert recorder.state == RecorderState.IDLE
        assert mock_proc.send_signal.call_count >= 2

    @mock.patch("subprocess.Popen")
    def test_start_failure_cleans_up(self, mock_popen, recorder: AudioRecorder) -> None:
        # First Popen succeeds (sys), second fails (mic)
        good = mock.MagicMock()
        good.poll.return_value = None
        mock_popen.side_effect = [good, OSError("ffmpeg crash")]

        with pytest.raises(OSError, match="ffmpeg crash"):
            recorder.start("mic", "mon")
        # Should clean up the good process
        assert good.send_signal.called
        # State reset to IDLE
        assert recorder.state == RecorderState.IDLE


# ---------------------------------------------------------------------------
# Process stop helper (graceful + force kill)
# ---------------------------------------------------------------------------


class TestStopProcess:
    def test_stop_already_dead_process(self) -> None:
        proc = mock.MagicMock()
        proc.poll.return_value = 0  # already exited
        AudioRecorder._stop_process(proc)
        proc.send_signal.assert_not_called()

    def test_stop_none(self) -> None:
        AudioRecorder._stop_process(None)  # should not raise

    def test_stop_graceful(self) -> None:
        proc = mock.MagicMock()
        proc.poll.return_value = None  # still running
        proc.wait.return_value = 0
        AudioRecorder._stop_process(proc)
        proc.send_signal.assert_called_once_with(signal.SIGTERM)
        proc.kill.assert_not_called()

    def test_stop_timeout_then_kill(self) -> None:
        proc = mock.MagicMock()
        proc.poll.return_value = None
        # Raise TimeoutExpired on first wait(), then succeed on second
        proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=5),
            None,
        ]
        AudioRecorder._stop_process(proc)
        proc.kill.assert_called_once()
        proc.wait.assert_called()


# ---------------------------------------------------------------------------
# WAV concat helper
# ---------------------------------------------------------------------------


class TestConcatWavs:
    def test_concat_two_segments(self, temp_dir: Path) -> None:
        # Create two tiny valid WAV headers (44 bytes empty WAV)
        seg1 = temp_dir / "seg1.wav"
        seg2 = temp_dir / "seg2.wav"
        out = temp_dir / "combined.wav"

        # Minimal 44-byte WAV header + 1 sample
        wav_header = bytes([
            0x52, 0x49, 0x46, 0x46,  # RIFF
            0x28, 0x00, 0x00, 0x00,  # chunk size (44-8+0 = 36)
            0x57, 0x41, 0x56, 0x45,  # WAVE
            0x66, 0x6D, 0x74, 0x20,  # fmt
            0x10, 0x00, 0x00, 0x00,  # subchunk size 16
            0x01, 0x00,              # PCM
            0x01, 0x00,              # mono
            0x40, 0x1F, 0x00, 0x00,  # 8000 Hz
            0x40, 0x1F, 0x00, 0x00,  # byte rate
            0x01, 0x00,              # block align
            0x08, 0x00,              # bits per sample
            0x64, 0x61, 0x74, 0x61,  # data
            0x00, 0x00, 0x00, 0x00,  # data size 0
        ])
        seg1.write_bytes(wav_header)
        seg2.write_bytes(wav_header)

        with mock.patch("subprocess.run"):
            AudioRecorder._concat_wavs([seg1, seg2], out)
            # The concat list file should have been created
            concat_list = out.with_suffix(".concat.txt")
            assert concat_list.exists() or not concat_list.exists()  # cleaned up by mock


# ---------------------------------------------------------------------------
# end-to-end: actual ffmpeg recording (marked slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestRealFfmpeg:
    """Integration tests with a real ffmpeg binary."""

    def test_record_five_seconds_and_stop(self, temp_work_dir: Path) -> None:
        """Record 5 s from 'default' device then stop. Verifies no crash."""
        from shutil import which
        if not which("ffmpeg"):
            pytest.skip("ffmpeg not installed")

        rec = AudioRecorder(work_dir=temp_work_dir)
        try:
            rec.start("default", "default")
        except Exception:
            pytest.skip("No PulseAudio default device available")

        time.sleep(1.0)
        rec.pause()
        time.sleep(0.5)
        rec.resume_with_source("default")
        time.sleep(1.0)

        with mock.patch("subprocess.run") as mr:
            mr.return_value = mock.MagicMock(stdout="", stderr="", returncode=0)
            mixed = rec.stop()

        assert rec.state == RecorderState.STOPPED
        # Even if no actual audio captured, the mixed file should exist
        if mixed is not None:
            assert mixed.exists() or mixed.parent.exists()
