"""Run transcription in a background thread with progress callbacks."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from main import TranscriptionConfig, transcribe_and_diarize, render_transcript, write_outputs


ProgressCallback = Callable[[str, float | None], None]
"""Args: (stage_name, progress_fraction_or_None)."""


class TranscriptionRunner:
    """Runs the WhisperX pipeline in a background thread.

    Reports progress via callbacks so the GUI can display a spinner / status.
    """

    def __init__(
        self,
        config: TranscriptionConfig,
        progress_callback: ProgressCallback | None = None,
        done_callback: Callable[[dict[str, Any] |
                                 None, str | None], None] | None = None,
    ) -> None:
        self._config = config
        self._progress = progress_callback
        self._done = done_callback
        self._thread: threading.Thread | None = None
        self._cancelled = False

    def start(self, audio_path: Path, output_dir: Path) -> None:
        """Launch transcription in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Transcription already in progress")
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run,
            args=(audio_path, output_dir),
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Request cancellation (best-effort — cannot interrupt WhisperX mid-call)."""
        self._cancelled = True

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _report(self, stage: str, fraction: float | None = None) -> None:
        if self._progress:
            try:
                self._progress(stage, fraction)
            except Exception:
                pass

    def _run(self, audio_path: Path, output_dir: Path) -> None:
        result: dict[str, Any] | None = None
        error: str | None = None

        try:
            self._report("Loading model …", 0.0)
            if self._cancelled:
                return

            self._report("Transcribing …", 0.1)
            result = transcribe_and_diarize(audio_path, config=self._config)

            self._report("Writing output …", 0.9)
            transcript_text = render_transcript(result, [])
            write_outputs(result, transcript_text, output_dir)

            self._report("Done", 1.0)
        except Exception:
            error = traceback.format_exc()
        finally:
            if self._done:
                try:
                    self._done(result, error)
                except Exception:
                    pass
