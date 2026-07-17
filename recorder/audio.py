"""Manage ffmpeg subprocess for dual-source (mic + system audio) recording.

Records mic and system-audio monitor to separate WAV files simultaneously.
On pause, only the mic stream is stopped; system audio keeps recording.
On stop, both streams are terminated and mixed into a single 16 kHz mono WAV.
"""

from __future__ import annotations

import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable


class RecorderState(Enum):
    IDLE = auto()
    RECORDING = auto()
    PAUSED = auto()  # mic paused, system audio still recording
    STOPPED = auto()


@dataclass
class RecorderStatus:
    state: RecorderState
    elapsed_seconds: float = 0.0
    mic_file: Path | None = None
    system_file: Path | None = None
    mixed_file: Path | None = None


class AudioRecorder:
    """Dual-source audio recorder backed by ffmpeg subprocesses.

    Two independent ffmpeg processes:
    - *mic* records the selected microphone source
    - *sys* records the selected monitor (system-audio loopback) source

    Pause / resume only affects the mic process so that system audio is
    captured continuously.
    """

    def __init__(self, work_dir: Path | None = None) -> None:
        self._work_dir = work_dir or Path.home() / ".cache" / "whisper-recorder"
        self._work_dir.mkdir(parents=True, exist_ok=True)

        self._mic_proc: subprocess.Popen[str] | None = None
        self._sys_proc: subprocess.Popen[str] | None = None
        self._state = RecorderState.IDLE
        self._start_time: float = 0.0
        self._pause_offset: float = 0.0  # accumulated paused time
        self._pause_start: float = 0.0

        # File paths
        self._mic_path = self._work_dir / "mic.wav"
        self._sys_path = self._work_dir / "system.wav"
        self._mixed_path = self._work_dir / "recording.wav"
        self._mic_segments: list[Path] = []

        self._lock = threading.Lock()
        self._status_callback: Callable[[RecorderStatus], None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> RecorderState:
        with self._lock:
            return self._state

    @property
    def elapsed(self) -> float:
        """Elapsed recording time in seconds (excluding paused periods)."""
        with self._lock:
            if self._state == RecorderState.IDLE:
                return 0.0
            if self._state == RecorderState.PAUSED:
                return self._pause_offset - self._start_time
            if self._state == RecorderState.STOPPED:
                return self._pause_offset - self._start_time
            return time.monotonic() - self._start_time  # RECORDING

    def set_status_callback(self, cb: Callable[[RecorderStatus], None] | None) -> None:
        self._status_callback = cb

    def start(self, mic_source: str, monitor_source: str) -> None:
        """Start recording from *mic_source* and *monitor_source*.

        Args:
            mic_source: PulseAudio source name for the microphone
            monitor_source: PulseAudio source name for the system-audio monitor
        """
        with self._lock:
            if self._state != RecorderState.IDLE:
                raise RuntimeError(f"Cannot start in state {self._state}")
            self._state = RecorderState.RECORDING
            self._start_time = time.monotonic()
            self._pause_offset = 0.0
            self._mic_segments = []

        # Clean stale files
        for p in [self._mic_path, self._sys_path, self._mixed_path]:
            p.unlink(missing_ok=True)

        try:
            self._sys_proc = self._launch_ffmpeg(
                monitor_source, self._sys_path)
            self._mic_proc = self._launch_ffmpeg(mic_source, self._mic_path)
        except Exception:
            self._cleanup_processes()
            with self._lock:
                self._state = RecorderState.IDLE
            raise

        self._notify()

    def pause(self) -> None:
        """Pause microphone recording only. System audio keeps recording."""
        with self._lock:
            if self._state != RecorderState.RECORDING:
                return
            self._state = RecorderState.PAUSED
            self._pause_start = time.monotonic()

        self._stop_process(self._mic_proc)
        self._mic_proc = None
        self._notify()

    def stop(self) -> Path | None:
        """Stop recording, mix streams, return path to mixed WAV.

        Returns ``None`` if the recorder was idle.
        """
        with self._lock:
            if self._state in (RecorderState.IDLE, RecorderState.STOPPED):
                return None
            self._state = RecorderState.STOPPED

        self._stop_process(self._mic_proc)
        self._mic_proc = None
        self._stop_process(self._sys_proc)
        self._sys_proc = None

        # If mic file exists, add current segment
        if self._mic_path.exists():
            segment_idx = len(self._mic_segments)
            segment_path = self._work_dir / f"mic_{segment_idx:03d}.wav"
            self._mic_path.rename(segment_path)
            self._mic_segments.append(segment_path)

        mixed = self._mix_segments()
        self._notify()
        return mixed

    def discard(self) -> None:
        """Kill all processes and delete recorded files."""
        self._stop_process(self._mic_proc)
        self._mic_proc = None
        self._stop_process(self._sys_proc)
        self._sys_proc = None

        for p in self._mic_segments:
            p.unlink(missing_ok=True)
        for p in [self._mic_path, self._sys_path, self._mixed_path]:
            p.unlink(missing_ok=True)

        with self._lock:
            self._state = RecorderState.IDLE
            self._start_time = 0.0
            self._pause_offset = 0.0
            self._mic_segments = []

        self._notify()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _launch_ffmpeg(self, source: str, output: Path) -> subprocess.Popen[str]:
        """Start ffmpeg recording a single PulseAudio source."""
        return subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-loglevel", "error",
                "-f", "pulse",
                "-i", source if source != "default" else "default",
                "-ar", "16000",
                "-ac", "1",
                "-f", "wav",
                str(output),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    @staticmethod
    def _stop_process(proc: subprocess.Popen[str] | None) -> None:
        """Gracefully stop a subprocess."""
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _cleanup_processes(self) -> None:
        self._stop_process(self._mic_proc)
        self._stop_process(self._sys_proc)
        self._mic_proc = None
        self._sys_proc = None

    def resume_with_source(self, mic_source: str) -> None:
        """Resume with an explicit mic source (called from GUI)."""
        with self._lock:
            if self._state != RecorderState.PAUSED:
                return
            self._pause_offset += time.monotonic() - self._pause_start
            self._state = RecorderState.RECORDING

        segment_idx = len(self._mic_segments)
        segment_path = self._work_dir / f"mic_{segment_idx:03d}.wav"
        self._mic_segments.append(segment_path)

        if self._mic_path.exists():
            self._mic_path.rename(segment_path)

        self._mic_proc = self._launch_ffmpeg(mic_source, self._mic_path)
        self._notify()

    def _mix_segments(self) -> Path | None:
        """Concatenate mic segments, then mix with system audio into 16 kHz mono."""
        # Build combined mic file
        mic_combined = self._work_dir / "mic_combined.wav"
        if len(self._mic_segments) >= 1:
            if len(self._mic_segments) == 1:
                # Single segment — just rename/copy
                if self._mic_segments[0].exists():
                    self._mic_segments[0].rename(mic_combined)
                else:
                    return None
            else:
                self._concat_wavs(self._mic_segments, mic_combined)
        else:
            return None

        sys_exists = self._sys_path.exists()

        if not sys_exists:
            # No system audio — mic only
            mic_combined.rename(self._mixed_path)
            return self._mixed_path

        # Mix: mic + system audio
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel", "error",
                "-i", str(mic_combined),
                "-i", str(self._sys_path),
                "-filter_complex",
                "[0][1]amix=inputs=2:duration=first:dropout_transition=3",
                "-ar", "16000",
                "-ac", "1",
                "-f", "wav",
                str(self._mixed_path),
            ],
            check=True,
        )
        return self._mixed_path

    @staticmethod
    def _concat_wavs(segments: list[Path], output: Path) -> None:
        """Concatenate WAV files using ffmpeg concat demuxer."""
        concat_list = output.with_suffix(".concat.txt")
        lines = [f"file '{p.resolve()}'" for p in segments if p.exists()]
        concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel", "error",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(output),
            ],
            check=True,
        )
        concat_list.unlink(missing_ok=True)

    def _notify(self) -> None:
        if self._status_callback is None:
            return
        with self._lock:
            state = self._state
        self._status_callback(
            RecorderStatus(
                state=state,
                elapsed_seconds=self.elapsed,
                mic_file=self._mic_path if self._mic_path.exists() else None,
                system_file=self._sys_path if self._sys_path.exists() else None,
                mixed_file=self._mixed_path if self._mixed_path.exists() else None,
            )
        )
