"""Manage ffmpeg subprocess for dual-source (mic + system audio) recording.

Records mic and system-audio monitor to separate WAV files simultaneously.
On pause, only the mic stream is stopped; system audio keeps recording.
On stop, both streams are terminated and mixed into a single 16 kHz mono WAV.
"""

from __future__ import annotations

import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable

_RMS_RE = re.compile(r"RMS_level=(-?[\d.]+|-inf)")


def _rms_db_to_level(db_text: str) -> float:
    """Map an RMS dBFS reading to a 0-100 meter level, clamped."""
    if db_text == "-inf":
        return 0.0
    db = float(db_text)
    return max(0.0, min(100.0, (db + 60.0) / 60.0 * 100.0))


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
        self._mic_level: float = 0.0
        self._state = RecorderState.IDLE
        self._start_time: float = 0.0  # monotonic timestamp of last start/resume
        self._accumulated: float = 0.0  # total active recording time before last pause
        self._pause_start: float = 0.0  # monotonic timestamp of last pause

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
    def mic_level(self) -> float:
        """Current mic input level, 0-100 (RMS-based)."""
        with self._lock:
            return self._mic_level

    @property
    def elapsed(self) -> float:
        """Elapsed recording time in seconds (excluding paused periods)."""
        with self._lock:
            if self._state == RecorderState.IDLE:
                return 0.0
            if self._state == RecorderState.PAUSED:
                return self._accumulated + (self._pause_start - self._start_time)
            if self._state == RecorderState.STOPPED:
                return self._accumulated
            # RECORDING: last active segment since start_time
            return self._accumulated + (time.monotonic() - self._start_time)

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
            self._accumulated = 0.0
            self._mic_segments = []

        # Clean stale files
        for p in [self._mic_path, self._sys_path, self._mixed_path]:
            p.unlink(missing_ok=True)

        try:
            self._sys_proc = self._launch_ffmpeg(
                monitor_source, self._sys_path)
            self._mic_proc = self._launch_ffmpeg(
                mic_source, self._mic_path, with_level_meter=True)
            self._start_level_reader(self._mic_proc)
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
            now = time.monotonic()
            self._accumulated += now - self._start_time
            self._state = RecorderState.PAUSED
            self._pause_start = now

        self._stop_process(self._mic_proc)
        self._mic_proc = None
        with self._lock:
            self._mic_level = 0.0
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
        with self._lock:
            self._mic_level = 0.0

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
            self._accumulated = 0.0
            self._mic_segments = []
            self._mic_level = 0.0

        self._notify()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _launch_ffmpeg(
        self, source: str, output: Path, with_level_meter: bool = False
    ) -> subprocess.Popen[str]:
        """Start ffmpeg recording a single PulseAudio source."""
        # "file=pipe\\:2" on the ametadata filter fails to initialize the
        # filter graph on some ffmpeg builds (silently crashes the process,
        # producing no output at all) — instead let ametadata print to its
        # normal av_log stream, which requires -loglevel info to be visible.
        loglevel = "info" if with_level_meter else "error"
        args = [
            "ffmpeg",
            "-y",
            "-loglevel", loglevel,
            "-f", "pulse",
            "-i", source if source != "default" else "default",
            "-ar", "16000",
            "-ac", "1",
        ]
        if with_level_meter:
            args += [
                "-af",
                "asetnsamples=n=1600:p=0,astats=metadata=1:reset=1,"
                "ametadata=print:key=lavfi.astats.Overall.RMS_level",
            ]
        args += ["-f", "wav", str(output)]
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _start_level_reader(self, proc: subprocess.Popen[str]) -> None:
        """Read ffmpeg's stderr in a daemon thread, updating ``_mic_level``."""
        def _reader() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                match = _RMS_RE.search(line)
                if match is None:
                    continue
                with self._lock:
                    self._mic_level = _rms_db_to_level(match.group(1))

        threading.Thread(target=_reader, daemon=True).start()

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
            self._state = RecorderState.RECORDING
            self._start_time = time.monotonic()

        segment_idx = len(self._mic_segments)
        segment_path = self._work_dir / f"mic_{segment_idx:03d}.wav"
        self._mic_segments.append(segment_path)

        if self._mic_path.exists():
            self._mic_path.rename(segment_path)

        self._mic_proc = self._launch_ffmpeg(
            mic_source, self._mic_path, with_level_meter=True)
        self._start_level_reader(self._mic_proc)
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
