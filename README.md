# whisper-diarize

Two tools in one repo:

1. **`whisper-transcribe`** — Batch-transcribe and diarize MP4 files via [WhisperX](https://github.com/m-bain/whisperX). Drop `.mp4` files into `input/`, run, get a timestamped speaker-labeled transcript.
2. **`whisper-recorder`** — GUI app for live recording (microphone + system audio) then transcribing. Global hotkey toggles a recording modal; results land in `~/WhisperRecordings/`.

## Requirements

| What                                 | Why                                                            |
| ------------------------------------ | -------------------------------------------------------------- |
| **Python ≥ 3.10**                    | Project runtime                                                |
| **[uv](https://docs.astral.sh/uv/)** | Package manager / virtualenv                                   |
| **ffmpeg + ffprobe**                 | Audio extraction, concatenation, encoding                      |
| **PulseAudio or PipeWire**           | Required by `whisper-recorder` for audio capture + device list |
| **tkinter** (python3-tk)             | Required by `whisper-recorder` GUI                             |
| **GPU** recommended (CUDA)           | CPU works but is slow                                          |
| **Hugging Face token**               | Needed for diarization + model access                          |

Accept user agreements on Hugging Face:

- [pyannote/segmentation-3.0](https://hf.co/pyannote/segmentation-3.0)
- [pyannote/speaker-diarization-3.1](https://hf.co/pyannote/speaker-diarization-3.1)
- The Whisper model you pick (e.g. `large-v3`)

## Install

```bash
# 1. System dependencies (Ubuntu / Debian)
sudo apt install ffmpeg pulseaudio python3-tk

# For PipeWire users:
sudo apt install pipewire-pulse

# 2. Clone + install Python deps
git clone https://github.com/theUpsider/whisper-diarize.git
cd whisper-diarize
uv sync
```

## Environment file

Copy the template and fill in your token:

```bash
cp .env.example .env
# Edit .env → add your Hugging Face token
```

```env
HUGGINGFACE_TOKEN=hf_your_token_here
```

Get your token at https://hf.co/settings/tokens. Also accepted via `--hf-token` CLI flag or `HF_TOKEN` env var.

---

## 1. CLI: `whisper-transcribe` — Batch MP4 Processing

Transcribes + diarizes all `.mp4` files in `input/`, ordered by creation time.

### Usage

```bash
# Place MP4 files in input/
cp /path/to/videos/*.mp4 input/

# Run
uv run whisper-transcribe

# Or with options:
uv run whisper-transcribe --language en --num-speakers 3
```

After running, input files are **moved** to `input_processed/`. Output lands in `output/<timestamp>/`.

### Options

| Flag             | Default    | Description                                      |
| ---------------- | ---------- | ------------------------------------------------ |
| `--input-dir`    | `./input`  | Folder with `.mp4` files                         |
| `--work-dir`     | `./work`   | Intermediate files (merged video, WAV)           |
| `--output-dir`   | `./output` | Final transcript files                           |
| `--language`     | `de`       | Language code                                    |
| `--model`        | `large-v3` | Whisper model                                    |
| `--batch-size`   | `8`        | Batch size                                       |
| `--compute-type` | `float16`  | `float16`, `float32`, or `int8`                  |
| `--device`       | _auto_     | `cuda` or `cpu`                                  |
| `--hf-token`     | _env_      | Hugging Face token                               |
| `--min-speakers` | —          | Min speaker count                                |
| `--max-speakers` | —          | Max speaker count                                |
| `--num-speakers` | —          | Exact speaker count                              |
| `--skip-concat`  | —          | Skip concat, use existing `work/<ts>/merged.wav` |

### Output

`output/<timestamp>/final_transcript.txt`:

```
Source files in concatenation order:
- 2026-01-15T10:30:00+00:00 (creation_time): meeting_part1.mp4
- 2026-01-15T11:00:00+00:00 (creation_time): meeting_part2.mp4

Transcript:

[00:00:00.000 - 00:00:05.200] SPEAKER_00: Hello everyone, let's get started.
[00:00:05.200 - 00:00:12.800] SPEAKER_01: Thanks for joining the call today.
```

`output/<timestamp>/final_transcript.json` — full WhisperX alignment + diarization result.

### Example: English, exact 3 speakers, CPU only

```bash
uv run whisper-transcribe --language en --num-speakers 3 --device cpu
```

### Example: Skip concat (re-run diarization on existing audio)

```bash
uv run whisper-transcribe --skip-concat --num-speakers 4
```

---

## 2. GUI: `whisper-recorder` — Live Recording

Tkinter app for recording your microphone + system audio, then transcribing.

### Launch

```bash
uv run whisper-recorder
```

- Press **Ctrl+Alt+R** (configurable) to toggle the recording modal
- Select mic and system-audio sources from dropdowns
- Hit **Record** → **Pause** (mic-only) / **Resume** → **Stop** → **Transcribe**
- Transcripts land in `~/WhisperRecordings/<timestamp>/`

### Desktop launcher (Linux)

```bash
uv run whisper-recorder --install-desktop
```

Adds a `Whisper Recorder` entry to your application launcher.

### Configuration

Stored at `~/.config/whisper-recorder/config.json`, created automatically with these defaults on first launch:

```json
{
  "hotkey": "<ctrl>+<alt>+r",
  "mic_device": "default",
  "monitor_device": "default",
  "language": "de",
  "model": "large-v3",
  "compute_type": "float16",
  "batch_size": 8,
  "output_dir": "~/WhisperRecordings",
  "auto_transcribe": false,
  "min_speakers": null,
  "max_speakers": null,
  "num_speakers": null
}
```

Edit this file to change defaults. Microphone, system-audio device, language, and model selections made in the GUI are saved back to this file automatically, so they persist across restarts. The hotkey is configured via this file only (no in-GUI editor). The Hugging Face token is **never** stored in config — it always comes from the `HUGGINGFACE_TOKEN` or `HF_TOKEN` environment variable.

### Wayland note

Global hotkeys (Ctrl+Alt+R) **do not work on Wayland**. The app still runs — just launch it manually and click **Record** in the modal. A warning is shown in the UI.

---

## Generate meeting minutes

This repository includes the **`transkript-protokoll`** skill (`.github/skills/transkript-protokoll/SKILL.md`) — a reusable agent skill that turns the final transcript into compact, professional German meeting minutes (Markdown + PDF).

### Using the skill with Copilot

The skill is auto-discovered by GitHub Copilot agents working in this workspace. After running transcription, ask any agent:

> "Use the transkript-protokoll skill on output/final_transcript.txt to generate meeting minutes."

The agent will:

- Assign speakers using contextual clues
- Condense small talk and repetition
- Extract decisions, key points, open questions, and action items
- Output `.md` and `.pdf` files

### Using the skill outside this workspace

The `.github/skills/transkript-protokoll/` folder is self-contained. Copy it into any other project's `.github/skills/` directory or post it to **Tagity** / **Touchitivity** — both platforms can create a skill from this folder structure.

---

## Project structure

```
whisper-diarize/
├── main.py                               # CLI entry point (whisper-transcribe)
├── recorder/                             # GUI live-recorder module
│   ├── main.py                           # Entry point (whisper-recorder)
│   ├── gui.py                            # tkinter modal UI
│   ├── audio.py                          # ffmpeg dual-source recording
│   ├── devices.py                        # PulseAudio source enumeration
│   ├── pipeline.py                       # Background transcription runner
│   ├── hotkey.py                         # Global hotkey (X11 only)
│   └── config.py                         # ~/.config/whisper-recorder/config.json
├── assets/
│   └── whisper-recorder.desktop          # Desktop file template
├── pyproject.toml                        # uv project config + deps + entry points
├── .env.example                          # HUGGINGFACE_TOKEN template
├── .github/
│   ├── copilot-instructions.md           # Copilot agent instructions
│   └── skills/
│       └── transkript-protokoll/         # Agent skill: transcript → protocol
│           ├── SKILL.md
│           ├── agents/
│           ├── assets/
│           │   └── protokoll-vorlage.md
│           └── references/
│               ├── agent-prompt.md
│               └── team-sprecherzuordnung.md
├── input/                                # Drop .mp4 files here (CLI)
├── input_processed/                      # Processed files moved here (CLI)
├── work/                                 # Intermediate per-run (merged.mp4, merged.wav)
├── output/                               # Transcripts per-run
└── tests/                                # Test files
```
