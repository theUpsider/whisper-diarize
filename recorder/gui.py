"""tkinter recording modal — the main GUI."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import pystray
from PIL import Image, ImageDraw
from pynput.keyboard import HotKey

from recorder.audio import AudioRecorder, RecorderState, RecorderStatus
from recorder.config import AppConfig, load_config, save_config
from recorder.devices import (
    AudioDevice,
    get_mics,
    get_monitors,
    list_devices,
    resolve_monitor_source,
)
from recorder.hotkey import HotkeyManager, is_wayland
from recorder.pipeline import TranscriptionRunner
from main import TranscriptionConfig


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAD_X = 12
PAD_Y = 8

# Tk keysym -> pynput modifier name, for hotkey capture.
MODIFIER_KEYSYMS = {
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Alt_L": "alt", "Alt_R": "alt",
    "Shift_L": "shift", "Shift_R": "shift",
    "Super_L": "cmd", "Super_R": "cmd",
}

# Tk keysym -> pynput named-key spelling, for non-character hotkey keys.
SPECIAL_KEYSYMS = {
    "Escape": "esc", "Return": "enter", "Tab": "tab",
    "BackSpace": "backspace", "Delete": "delete", "Insert": "insert",
    "space": "space", "Up": "up", "Down": "down", "Left": "left",
    "Right": "right", "Home": "home", "End": "end",
    "Prior": "page_up", "Next": "page_down",
    **{f"F{i}": f"f{i}" for i in range(1, 21)},
}


# ---------------------------------------------------------------------------
# Device refresh helper
# ---------------------------------------------------------------------------

def _refresh_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Return (mics, monitors), falling back to the default mic on failure."""
    try:
        all_devs = list_devices()
        return get_mics(all_devs), get_monitors(all_devs)
    except Exception:
        default = AudioDevice(
            name="default", description="Default", is_monitor=False)
        return [default], []


def _tray_icon_image() -> Image.Image:
    """Draw a simple microphone glyph for the tray icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((24, 8, 40, 38), radius=8, fill=(220, 60, 60, 255))
    draw.line((32, 38, 32, 50), fill=(60, 60, 60, 255), width=4)
    draw.line((20, 52, 44, 52), fill=(60, 60, 60, 255), width=4)
    draw.arc((16, 24, 48, 52), start=0, end=180,
              fill=(60, 60, 60, 255), width=4)
    return img


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
        self._diarize_var: tk.BooleanVar | None = None
        self._autostart_var: tk.BooleanVar | None = None
        self._hotkey_var: tk.StringVar | None = None
        self._hotkey_capture_btn: ttk.Button | None = None
        self._hotkey_capture_mods: set[str] = set()
        self._timer_var: tk.StringVar | None = None
        self._status_var: tk.StringVar | None = None
        self._progress: ttk.Progressbar | None = None
        self._meter_var: tk.DoubleVar | None = None
        self._meter_bar: ttk.Progressbar | None = None
        self._meter_job: str | None = None
        self._button_frame: ttk.Frame | None = None
        self._wayland_label: ttk.Label | None = None
        self._recent_var: tk.StringVar | None = None
        self._recent_combo: ttk.Combobox | None = None
        self._recent_paths: list[Path] = []
        self._tray_icon: pystray.Icon | None = None

        # Mic source stored for resume
        self._current_mic_source: str = self._config.mic_device
        self._current_monitor_source: str = self._config.monitor_device

        # Set up recorder status callback
        self._recorder.set_status_callback(self._on_recorder_status)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self, show_modal: bool = True) -> None:
        """Start the GUI event loop."""
        if show_modal:
            self._show_modal()
        self._start_tray_icon()

        # Start hotkey polling
        self._hotkey.start()
        self._poll_hotkey()

        try:
            self._root.mainloop()
        except KeyboardInterrupt:
            self._quit()

    def _start_tray_icon(self) -> None:
        """Show a system-tray icon with a Close item to quit the app."""
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._tray_open, default=True),
            pystray.MenuItem("Close", self._tray_close),
        )
        tray_icon = pystray.Icon(
            "whisper-recorder", _tray_icon_image(), "Whisper Recorder", menu)
        self._tray_icon = tray_icon
        threading.Thread(target=tray_icon.run, daemon=True).start()

    def _tray_open(self, _icon: pystray.Icon, _item: object) -> None:
        # pystray callback runs off the Tk thread; hop back before touching Tk state.
        self._root.after(0, self._open_modal)

    def _tray_close(self, _icon: pystray.Icon, _item: object) -> None:
        # pystray callback runs off the Tk thread; hop back for a safe quit
        # (which also stops the tray icon).
        self._root.after(0, self._quit)

    def _quit(self) -> None:
        self._recorder.discard()
        self._hotkey.stop()
        if self._tray_icon is not None:
            self._tray_icon.stop()
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

    def _open_modal(self) -> None:
        """Show the modal, or bring it to the front if already open."""
        if self._modal_visible and self._modal is not None:
            self._modal.deiconify()
            self._modal.lift()
            self._modal.focus_force()
            return
        self._show_modal()

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
        self._modal.transient(self._root)
        self._modal_visible = True

        # Make truly modal (Windows only; no-op on X11/Wayland)
        try:
            self._root.wm_attributes("-disabled", True)
        except tk.TclError:
            pass

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
        self._mic_combo["values"] = ["default"] + [d.name for d in mics]
        self._mic_combo.pack(side="left", padx=(4, 16))
        self._mic_combo.bind("<<ComboboxSelected>>", self._persist_settings)

        ttk.Label(row1, text="System:").pack(side="left")
        monitor_source = resolve_monitor_source(
            self._config.monitor_device, monitors
        ) or ""
        self._monitor_var = tk.StringVar(value=monitor_source)
        self._monitor_combo = ttk.Combobox(
            row1, textvariable=self._monitor_var, state="readonly", width=35,
        )
        self._monitor_combo["values"] = [d.name for d in monitors]
        self._monitor_combo.pack(side="left", padx=(4, 0))
        self._monitor_combo.bind(
            "<<ComboboxSelected>>", self._persist_settings)

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
        lang_menu.bind("<<ComboboxSelected>>", self._persist_settings)

        ttk.Label(row2, text="Model:").pack(side="left")
        self._model_var = tk.StringVar(value=self._config.model)
        model_menu = ttk.Combobox(
            row2, textvariable=self._model_var, state="readonly", width=18,
        )
        model_menu["values"] = [
            "tiny", "base", "small", "medium", "large-v2", "large-v3", "turbo",
        ]
        model_menu.pack(side="left", padx=(4, 0))
        model_menu.bind("<<ComboboxSelected>>", self._persist_settings)

        self._diarize_var = tk.BooleanVar(value=self._config.diarize)
        diarize_check = ttk.Checkbutton(
            row2, text="Diarize speakers", variable=self._diarize_var,
            command=self._persist_settings,
        )
        diarize_check.pack(side="left", padx=(16, 0))

        # ---- Hotkey row ----
        row3 = ttk.Frame(main)
        row3.pack(fill="x", pady=(0, PAD_Y))

        ttk.Label(row3, text="Hotkey:").pack(side="left")
        self._hotkey_var = tk.StringVar(value=self._config.hotkey)
        hotkey_display = ttk.Label(
            row3, textvariable=self._hotkey_var, width=22,
            relief="sunken", anchor="center", padding=(4, 2),
        )
        hotkey_display.pack(side="left", padx=(4, 8))

        self._hotkey_capture_btn = ttk.Button(
            row3, text="Change…", command=self._start_hotkey_capture,
        )
        self._hotkey_capture_btn.pack(side="left")
        if is_wayland():
            self._hotkey_capture_btn.state(["disabled"])

        self._autostart_var = tk.BooleanVar(
            value=self._config.autostart_enabled)
        autostart_check = ttk.Checkbutton(
            row3, text="Launch at startup (minimized)",
            variable=self._autostart_var, command=self._on_autostart_toggle,
        )
        autostart_check.pack(side="left", padx=(16, 0))

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

        # ---- Level meter ----
        meter_frame = ttk.Frame(main)
        meter_frame.pack(fill="x", pady=(0, PAD_Y))
        ttk.Label(meter_frame, text="Level:").pack(side="left")
        self._meter_var = tk.DoubleVar(value=0.0)
        self._meter_bar = ttk.Progressbar(
            meter_frame, mode="determinate", maximum=100,
            variable=self._meter_var, length=200)
        self._meter_bar.pack(side="left", padx=(8, 0), fill="x", expand=True)

        # ---- Progress bar ----
        self._progress = ttk.Progressbar(
            main, mode="indeterminate", length=400)

        # ---- Buttons ----
        self._button_frame = ttk.Frame(main)
        self._button_frame.pack(fill="x", pady=(PAD_Y, 0))

        # ---- Recent recordings ----
        recent_frame = ttk.Frame(main)
        recent_frame.pack(fill="x", pady=(PAD_Y, 0))
        ttk.Label(recent_frame, text="Recent:").pack(side="left")
        self._recent_var = tk.StringVar(value="")
        self._recent_combo = ttk.Combobox(
            recent_frame, textvariable=self._recent_var, state="readonly", width=35,
        )
        self._recent_combo.pack(side="left", padx=(4, 0), fill="x", expand=True)
        self._recent_combo.bind(
            "<<ComboboxSelected>>", self._on_recent_selected)
        self._refresh_recent_recordings()

        self._update_buttons_idle()

        # Force geometry negotiation before locking size/centering — without
        # this the window manager can map the Toplevel at its pre-content
        # 1x1 size instead of auto-sizing to fit the packed widgets.
        self._modal.update_idletasks()
        w = self._modal.winfo_reqwidth()
        h = self._modal.winfo_reqheight()
        x = (self._modal.winfo_screenwidth() - w) // 2
        y = (self._modal.winfo_screenheight() - h) // 3
        self._modal.geometry(f"{w}x{h}+{x}+{y}")
        self._modal.resizable(False, False)
        self._modal.deiconify()
        self._modal.lift()
        self._modal.focus_force()

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
            self._button_frame, text="New Recording", command=self._on_new_recording,
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
            self._button_frame, text="New Recording", command=self._on_new_recording,
        ).pack(side="left")
        self._refresh_recent_recordings()

    def _update_buttons_error(self, msg: str) -> None:
        self._clear_buttons()
        assert self._status_var is not None
        assert self._progress is not None
        assert self._button_frame is not None
        self._progress.stop()
        self._progress.pack_forget()
        self._status_var.set(f"Error: {msg}")

        ttk.Button(
            self._button_frame, text="New Recording", command=self._on_new_recording,
        ).pack(side="left")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_record(self) -> None:
        assert self._mic_var is not None
        assert self._monitor_var is not None
        mic = self._mic_var.get() or "default"
        monitor = self._monitor_var.get()
        if not monitor:
            messagebox.showerror(
                "Recording Error",
                "No system-audio monitor source is available.",
            )
            return

        self._current_mic_source = mic
        self._current_monitor_source = monitor

        try:
            self._recorder.start(mic, monitor)
        except Exception as exc:
            messagebox.showerror("Recording Error", str(exc))
            return

        self._update_buttons_recording()
        self._start_timer()
        self._start_meter()

    def _on_pause(self) -> None:
        self._recorder.pause()
        self._update_buttons_paused()
        self._stop_timer()
        self._stop_meter()

    def _on_resume(self) -> None:
        # Pass the current mic source so AudioRecorder knows which device
        self._recorder.resume_with_source(self._current_mic_source)
        self._update_buttons_recording()
        self._start_timer()
        self._start_meter()

    def _on_stop(self) -> None:
        self._stop_timer()
        self._stop_meter()
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

    def _on_new_recording(self) -> None:
        if self._recorder.state != RecorderState.IDLE:
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
        audio_output = base_out / self._mixed_path.name
        shutil.copy2(self._mixed_path, audio_output)

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
            diarize=(self._diarize_var.get()
                     if self._diarize_var else self._config.diarize),
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
                self._notify_transcription_done()
                if self._config.auto_open_folder:
                    self._root.after(0, self._on_open_folder)

        self._transcriber = TranscriptionRunner(
            config=tcfg,
            progress_callback=progress,
            done_callback=done,
        )
        self._transcriber.start(audio_output, base_out)

    def _on_open_folder(self) -> None:
        if self._output_dir and self._output_dir.exists():
            subprocess.run(["xdg-open", str(self._output_dir)], check=False)

    def _refresh_recent_recordings(self) -> None:
        if self._recent_combo is None or self._recent_var is None:
            return
        output_dir = Path(self._config.output_dir)
        subdirs: list[Path] = []
        if output_dir.exists():
            subdirs = [p for p in output_dir.iterdir() if p.is_dir()]
            subdirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        self._recent_paths = subdirs[:10]
        self._recent_combo["values"] = [p.name for p in self._recent_paths]
        self._recent_var.set("")

    def _on_recent_selected(self, _event: object = None) -> None:
        if self._recent_combo is None:
            return
        index = self._recent_combo.current()
        if index < 0 or index >= len(self._recent_paths):
            return
        subprocess.run(
            ["xdg-open", str(self._recent_paths[index])], check=False)

    def _notify_transcription_done(self) -> None:
        if shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", "Whisper Recorder", "Transcription finished"],
                check=False,
            )

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
    # Level meter
    # ------------------------------------------------------------------

    def _start_meter(self) -> None:
        self._stop_meter()
        self._tick_meter()

    def _stop_meter(self) -> None:
        if self._meter_job is not None:
            self._root.after_cancel(self._meter_job)
            self._meter_job = None
        if self._meter_var is not None:
            self._meter_var.set(0.0)

    def _tick_meter(self) -> None:
        assert self._meter_var is not None
        self._meter_var.set(self._recorder.mic_level)
        self._meter_job = self._root.after(100, self._tick_meter)

    # ------------------------------------------------------------------
    # Recorder status callback (for external state changes)
    # ------------------------------------------------------------------

    def _on_recorder_status(self, status: RecorderStatus) -> None:
        del status  # unused — reserved for future use
        pass  # Handled by button state transitions; reserved for future use

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _persist_settings(self, _event: object = None) -> None:
        """Save current mic/monitor/language/model selection to disk."""
        assert self._mic_var is not None
        assert self._monitor_var is not None
        assert self._lang_var is not None
        assert self._model_var is not None
        assert self._diarize_var is not None
        self._config.mic_device = self._mic_var.get()
        self._config.monitor_device = self._monitor_var.get()
        self._config.language = self._lang_var.get()
        self._config.model = self._model_var.get()
        self._config.diarize = self._diarize_var.get()
        save_config(self._config)

    def _on_autostart_toggle(self) -> None:
        """Persist the autostart setting and (un)install the login .desktop file."""
        assert self._autostart_var is not None
        from recorder import main as recorder_main

        enabled = self._autostart_var.get()
        self._config.autostart_enabled = enabled
        save_config(self._config)
        if enabled:
            recorder_main.install_autostart()
        else:
            recorder_main.uninstall_autostart()

    # ------------------------------------------------------------------
    # Hotkey capture
    # ------------------------------------------------------------------

    def _start_hotkey_capture(self) -> None:
        assert self._hotkey_var is not None
        assert self._modal is not None
        self._hotkey_capture_mods = set()
        self._hotkey_var.set("Press keys… (Esc cancels)")
        if self._hotkey_capture_btn is not None:
            self._hotkey_capture_btn.state(["disabled"])
        self._modal.bind("<KeyPress>", self._on_hotkey_capture_key)
        self._modal.focus_set()

    def _end_hotkey_capture(self) -> None:
        if self._modal is not None:
            self._modal.unbind("<KeyPress>")
        if self._hotkey_capture_btn is not None:
            self._hotkey_capture_btn.state(["!disabled"])

    def _on_hotkey_capture_key(self, event: tk.Event) -> None:
        assert self._hotkey_var is not None
        keysym = event.keysym

        if keysym == "Escape":
            self._hotkey_var.set(self._config.hotkey)
            self._end_hotkey_capture()
            return

        if keysym in MODIFIER_KEYSYMS:
            self._hotkey_capture_mods.add(MODIFIER_KEYSYMS[keysym])
            return

        if keysym in SPECIAL_KEYSYMS:
            key = f"<{SPECIAL_KEYSYMS[keysym]}>"
        elif len(keysym) == 1:
            key = keysym.lower()
        else:
            return  # unrecognized key — keep waiting for a usable one

        if not self._hotkey_capture_mods:
            messagebox.showwarning(
                "Hotkey",
                "Hotkey must include at least one modifier (Ctrl/Alt/Shift/Super).",
            )
            self._hotkey_var.set(self._config.hotkey)
            self._end_hotkey_capture()
            return

        combo = "+".join(
            f"<{m}>" for m in sorted(self._hotkey_capture_mods)) + f"+{key}"

        try:
            HotKey.parse(combo)
        except ValueError:
            messagebox.showerror("Hotkey", f"Unsupported combination: {combo}")
            self._hotkey_var.set(self._config.hotkey)
            self._end_hotkey_capture()
            return

        self._config.hotkey = combo
        save_config(self._config)
        self._hotkey.hotkey = combo
        self._hotkey_var.set(combo)
        self._end_hotkey_capture()

    # ------------------------------------------------------------------
    # Device list refresh
    # ------------------------------------------------------------------

    def _refresh_device_lists(self) -> None:
        """Reload device lists and update dropdowns."""
        try:
            mics, monitors = _refresh_devices()
            if hasattr(self, '_mic_combo') and self._mic_combo is not None:
                assert self._mic_var is not None
                mic_names = ["default"] + [d.name for d in mics]
                self._mic_combo["values"] = mic_names
                if self._mic_var.get() not in mic_names:
                    self._mic_var.set("default")
            if hasattr(self, '_monitor_combo') and self._monitor_combo is not None:
                assert self._monitor_var is not None
                mon_names = [d.name for d in monitors]
                self._monitor_combo["values"] = mon_names
                monitor_source = resolve_monitor_source(
                    self._monitor_var.get(), monitors
                )
                self._monitor_var.set(monitor_source or "")
            logger.info("Device lists refreshed: %d mics, %d monitors",
                        len(mics), len(monitors))
        except Exception:
            logger.exception("Failed to refresh device list")
