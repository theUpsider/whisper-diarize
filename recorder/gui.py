"""tkinter recording modal — the main GUI."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from recorder.audio import AudioRecorder, RecorderState, RecorderStatus
from recorder.config import AppConfig, load_config
from recorder.devices import AudioDevice, get_mics, get_monitors, list_devices
from recorder.hotkey import HotkeyManager, is_wayland
from recorder.pipeline import TranscriptionRunner
from main import TranscriptionConfig


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAD_X = 12
PAD_Y = 8


# ---------------------------------------------------------------------------
# Device refresh helper
# ---------------------------------------------------------------------------

def _refresh_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Return (mics, monitors), falling back to [default] on failure."""
    try:
        all_devs = list_devices()
        return get_mics(all_devs), get_monitors(all_devs)
    except Exception:
        default = AudioDevice(
            name="default", description="Default", is_monitor=False)
        default_mon = AudioDevice(
            name="default", description="Default Monitor", is_monitor=True)
        return [default], [default_mon]


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class RecorderApp:
    """Tkinter root window (hidden) + modal recording dialog."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or load_config()
        self._recorder = AudioRecorder()
        self._hotkey = HotkeyManager(self._config.hotkey)
        self._transcriber: TranscriptionRunner | None = None
        self._mixed_path: Path | None = None
        self._output_dir: Path | None = None
        self._timer_job: str | None = None

        # Build the hidden root window
        self._root = tk.Tk()
        self._root.withdraw()  # hidden; only the modal is shown
        self._root.title("Whisper Recorder")
        self._root.protocol("WM_DELETE_WINDOW", self._quit)

        # Build the modal
        self._modal: tk.Toplevel | None = None
        self._modal_visible = False

        # Widgets that get rebuilt / updated
        self._mic_var: tk.StringVar | None = None
        self._mic_combo: ttk.Combobox | None = None
        self._monitor_var: tk.StringVar | None = None
        self._monitor_combo: ttk.Combobox | None = None
        self._lang_var: tk.StringVar | None = None
        self._model_var: tk.StringVar | None = None
        self._timer_var: tk.StringVar | None = None
        self._status_var: tk.StringVar | None = None
        self._progress: ttk.Progressbar | None = None
        self._button_frame: ttk.Frame | None = None
        self._wayland_label: ttk.Label | None = None

        # Mic source stored for resume
        self._current_mic_source: str = self._config.mic_device
        self._current_monitor_source: str = self._config.monitor_device

        # Set up recorder status callback
        self._recorder.set_status_callback(self._on_recorder_status)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the GUI event loop."""
        self._show_modal()

        # Start hotkey polling
        self._hotkey.start()
        self._poll_hotkey()

        try:
            self._root.mainloop()
        except KeyboardInterrupt:
            self._quit()

    def _quit(self) -> None:
        self._recorder.discard()
        self._hotkey.stop()
        if self._root:
            self._root.destroy()
        sys.exit(0)

    def _poll_hotkey(self) -> None:
        """Periodically check the hotkey queue (every 150 ms)."""
        if self._hotkey.poll():
            self._toggle_modal()
        self._root.after(150, self._poll_hotkey)

    # ------------------------------------------------------------------
    # Modal show / hide
    # ------------------------------------------------------------------

    def _show_modal(self) -> None:
        if self._modal_visible:
            return
        self._build_modal()
        self._modal_visible = True

    def _hide_modal(self) -> None:
        if not self._modal_visible:
            return
        # Don't hide while recording
        if self._recorder.state in (RecorderState.RECORDING, RecorderState.PAUSED):
            return
        # Re-enable the root window
        try:
            self._root.wm_attributes("-disabled", False)
        except tk.TclError:
            pass
        if self._modal:
            self._modal.destroy()
            self._modal = None
        self._modal_visible = False

    def _toggle_modal(self) -> None:
        if self._modal_visible:
            self._hide_modal()
        else:
            self._show_modal()

    # ------------------------------------------------------------------
    # Modal construction
    # ------------------------------------------------------------------

    def _build_modal(self) -> None:
        self._modal = tk.Toplevel(self._root)
        self._modal.title("Whisper Recorder")
        self._modal.resizable(False, False)
        self._modal.transient(self._root)

        # Make truly modal
        self._root.wm_attributes("-disabled", True)

        def _release() -> None:
            try:
                self._root.wm_attributes("-disabled", False)
            except tk.TclError:
                pass
            self._modal_visible = False

        self._modal.protocol("WM_DELETE_WINDOW", lambda m=self._modal: (
            _release(), m.destroy() if m is not None else None))

        main = ttk.Frame(self._modal, padding=(PAD_X, PAD_Y))
        main.pack(fill="both", expand=True)

        # ---- Wayland warning ----
        if is_wayland():
            wl = ttk.Label(
                main,
                text="⚠ Wayland: Hotkeys not available.\nLaunch this program to start recording.",
                foreground="#b45f06",
                justify="center",
            )
            wl.pack(pady=(0, PAD_Y))

        # ---- Device row ----
        mics, monitors = _refresh_devices()

        row1 = ttk.Frame(main)
        row1.pack(fill="x", pady=(0, PAD_Y))

        ttk.Label(row1, text="Mic:").pack(side="left")
        self._mic_var = tk.StringVar(value=self._config.mic_device)
        self._mic_combo = ttk.Combobox(
            row1, textvariable=self._mic_var, state="readonly", width=35,
        )
        self._mic_combo["values"] = [d.name for d in mics]
        self._mic_combo.pack(side="left", padx=(4, 16))

        ttk.Label(row1, text="System:").pack(side="left")
        self._monitor_var = tk.StringVar(value=self._config.monitor_device)
        self._monitor_combo = ttk.Combobox(
            row1, textvariable=self._monitor_var, state="readonly", width=35,
        )
        self._monitor_combo["values"] = [d.name for d in monitors]
        self._monitor_combo.pack(side="left", padx=(4, 0))

        btn_refresh = ttk.Button(
            row1, text="↻", width=3, command=self._refresh_device_lists)
        btn_refresh.pack(side="left", padx=(8, 0))

        # ---- Language / Model row ----
        row2 = ttk.Frame(main)
        row2.pack(fill="x", pady=(0, PAD_Y))

        ttk.Label(row2, text="Language:").pack(side="left")
        self._lang_var = tk.StringVar(value=self._config.language)
        lang_menu = ttk.Combobox(
            row2, textvariable=self._lang_var, state="readonly", width=8,
        )
        lang_menu["values"] = ["de", "en", "fr",
                               "es", "it", "nl", "pl", "auto"]
        lang_menu.pack(side="left", padx=(4, 16))

        ttk.Label(row2, text="Model:").pack(side="left")
        self._model_var = tk.StringVar(value=self._config.model)
        model_menu = ttk.Combobox(
            row2, textvariable=self._model_var, state="readonly", width=18,
        )
        model_menu["values"] = [
            "tiny", "base", "small", "medium", "large-v2", "large-v3", "turbo",
        ]
        model_menu.pack(side="left", padx=(4, 0))

        # ---- Timer + Status ----
        timer_frame = ttk.Frame(main)
        timer_frame.pack(fill="x", pady=PAD_Y)

        self._timer_var = tk.StringVar(value="00:00:00")
        timer_label = ttk.Label(
            timer_frame, textvariable=self._timer_var, font=("monospace", 22))
        timer_label.pack(side="left")

        self._status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(
            timer_frame, textvariable=self._status_var, foreground="gray")
        status_label.pack(side="left", padx=(16, 0))

        # ---- Progress bar ----
        self._progress = ttk.Progressbar(
            main, mode="indeterminate", length=400)

        # ---- Buttons ----
        self._button_frame = ttk.Frame(main)
        self._button_frame.pack(fill="x", pady=(PAD_Y, 0))

        self._update_buttons_idle()

    # ------------------------------------------------------------------
    # Button state management
    # ------------------------------------------------------------------

    def _clear_buttons(self) -> None:
        if self._button_frame is None:
            return
        for w in self._button_frame.winfo_children():
            w.destroy()

    def _update_buttons_idle(self) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._timer_var is not None
        assert self._button_frame is not None
        self._status_var.set("Ready")
        self._timer_var.set("00:00:00")

        ttk.Button(
            self._button_frame, text="●  Record", command=self._on_record,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            self._button_frame, text="Close", command=self._hide_modal,
        ).pack(side="right")

    def _update_buttons_recording(self) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._button_frame is not None
        self._status_var.set("Recording …")

        ttk.Button(
            self._button_frame, text="⏸  Pause Mic", command=self._on_pause,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            self._button_frame, text="■  Stop", command=self._on_stop,
        ).pack(side="left")

    def _update_buttons_paused(self) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._button_frame is not None
        self._status_var.set("Mic paused")

        ttk.Button(
            self._button_frame, text="▶  Resume Mic", command=self._on_resume,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            self._button_frame, text="■  Stop", command=self._on_stop,
        ).pack(side="left")

    def _update_buttons_stopped(self, elapsed: float) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._button_frame is not None
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        self._status_var.set(f"Stopped — {hours:02d}:{mins:02d}:{secs:02d}")

        ttk.Button(
            self._button_frame, text="📝  Transcribe", command=self._on_transcribe,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            self._button_frame, text="🗑  Discard", command=self._on_discard,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            self._button_frame, text="New Recording", command=self._update_buttons_idle,
        ).pack(side="left")

    def _update_buttons_transcribing(self) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._progress is not None
        assert self._button_frame is not None
        self._status_var.set("Transcribing …")
        self._progress.pack(fill="x", pady=(0, PAD_Y))
        self._progress.start(10)

    def _update_buttons_done(self) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._progress is not None
        assert self._button_frame is not None
        self._progress.stop()
        self._progress.pack_forget()
        self._status_var.set("Done!")

        ttk.Button(
            self._button_frame, text="📂  Open Folder", command=self._on_open_folder,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            self._button_frame, text="New Recording", command=self._update_buttons_idle,
        ).pack(side="left")

    def _update_buttons_error(self, msg: str) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._progress is not None
        assert self._button_frame is not None
        self._progress.stop()
        self._progress.pack_forget()
        self._status_var.set(f"Error: {msg}")

        ttk.Button(
            self._button_frame, text="New Recording", command=self._update_buttons_idle,
        ).pack(side="left")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_record(self) -> None:
        assert self._mic_var is not None
        assert self._monitor_var is not None
        mic = self._mic_var.get() or "default"
        monitor = self._monitor_var.get() or "default"

        self._current_mic_source = mic
        self._current_monitor_source = monitor

        try:
            self._recorder.start(mic, monitor)
        except Exception as exc:
            messagebox.showerror("Recording Error", str(exc))
            return

        self._update_buttons_recording()
        self._start_timer()

    def _on_pause(self) -> None:
        self._recorder.pause()
        self._update_buttons_paused()
        self._stop_timer()

    def _on_resume(self) -> None:
        # Pass the current mic source so AudioRecorder knows which device
        self._recorder.resume_with_source(self._current_mic_source)
        self._update_buttons_recording()
        self._start_timer()

    def _on_stop(self) -> None:
        self._stop_timer()
        try:
            self._mixed_path = self._recorder.stop()
        except Exception as exc:
            messagebox.showerror("Stop Error", str(exc))
            self._update_buttons_idle()
            return

        elapsed = self._recorder.elapsed
        self._update_buttons_stopped(elapsed)

    def _on_discard(self) -> None:
        self._recorder.discard()
        self._mixed_path = None
        self._update_buttons_idle()

    def _on_transcribe(self) -> None:
        if self._mixed_path is None or not self._mixed_path.exists():
            messagebox.showwarning(
                "No Recording", "No recording to transcribe.")
            return

        self._update_buttons_transcribing()

        # Determine output directory
        ts = time.strftime("%Y-%m-%d_%H%M%S")
        base_out = Path(self._config.output_dir) / ts
        base_out.mkdir(parents=True, exist_ok=True)
        self._output_dir = base_out

        tcfg = TranscriptionConfig(
            hf_token=self._config.hf_token,
            model=(self._model_var.get()
                   if self._model_var else self._config.model),
            language=(self._lang_var.get()
                      if self._lang_var else self._config.language),
            compute_type=self._config.compute_type,
            batch_size=self._config.batch_size,
            min_speakers=self._config.min_speakers,
            max_speakers=self._config.max_speakers,
            num_speakers=self._config.num_speakers,
        )

        def progress(stage: str, fraction: float | None) -> None:
            del fraction  # unused — required by TranscriptionRunner callback signature
            assert self._status_var is not None
            status_var: tk.StringVar = self._status_var  # narrow for closure
            self._root.after(0, lambda sv=status_var, s=stage: sv.set(s))

        def done(result: object, error: str | None) -> None:
            del result  # unused — required by TranscriptionRunner callback signature
            if error:
                self._root.after(0, lambda: self._update_buttons_error(
                    error.splitlines()[-1]))
                logger.error("Transcription failed:\n%s", error)
            else:
                self._root.after(0, self._update_buttons_done)

        self._transcriber = TranscriptionRunner(
            config=tcfg,
            progress_callback=progress,
            done_callback=done,
        )
        self._transcriber.start(self._mixed_path, base_out)

    def _on_open_folder(self) -> None:
        if self._output_dir and self._output_dir.exists():
            subprocess.run(["xdg-open", str(self._output_dir)], check=False)

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        self._stop_timer()
        self._tick_timer()

    def _stop_timer(self) -> None:
        if self._timer_job is not None:
            self._root.after_cancel(self._timer_job)
            self._timer_job = None

    def _tick_timer(self) -> None:
        assert self._timer_var is not None
        elapsed = self._recorder.elapsed
        hours, rem = divmod(int(elapsed), 3600)
        mins, secs = divmod(rem, 60)
        self._timer_var.set(f"{hours:02d}:{mins:02d}:{secs:02d}")
        self._timer_job = self._root.after(250, self._tick_timer)

    # ------------------------------------------------------------------
    # Recorder status callback (for external state changes)
    # ------------------------------------------------------------------

    def _on_recorder_status(self, status: RecorderStatus) -> None:
        del status  # unused — reserved for future use
        pass  # Handled by button state transitions; reserved for future use

    # ------------------------------------------------------------------
    # Device list refresh
    # ------------------------------------------------------------------

    def _refresh_device_lists(self) -> None:
        """Reload device lists and update dropdowns."""
        try:
            mics, monitors = _refresh_devices()
            if hasattr(self, '_mic_combo') and self._mic_combo is not None:
                assert self._mic_var is not None
                mic_names = [d.name for d in mics]
                self._mic_combo["values"] = mic_names
                if self._mic_var.get() not in mic_names:
                    self._mic_var.set(mic_names[0] if mic_names else "default")
            if hasattr(self, '_monitor_combo') and self._monitor_combo is not None:
                assert self._monitor_var is not None
                mon_names = [d.name for d in monitors]
                self._monitor_combo["values"] = mon_names
                if self._monitor_var.get() not in mon_names:
                    self._monitor_var.set(
                        mon_names[0] if mon_names else "default")
            logger.info("Device lists refreshed: %d mics, %d monitors",
                        len(mics), len(monitors))
        except Exception:
            logger.exception("Failed to refresh device list")
