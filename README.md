# whisper-diarize

Transcribe and diarize MP4 video files using [WhisperX](https://github.com/m-bain/whisperX). Drops `.mp4` files into `input/`, runs the script, and gets a timestamped, speaker-labeled transcript in `output/`.

## Features

- Concatenates all `.mp4` files from `input/` (ordered by creation time from ffprobe, fallback to mtime)
- Extracts 16kHz mono WAV
- Transcribes with WhisperX (large-v3 by default)
- Aligns word-level timestamps
- Diarizes speakers via pyannote.audio (Hugging Face token required)
- Outputs readable transcript + raw JSON

## Requirements

- **Python ≥ 3.10**
- **[uv](https://docs.astral.sh/uv/)** — package manager / virtualenv
- **ffmpeg + ffprobe** — must be on `$PATH`
- **GPU** recommended (CUDA); CPU works but slow
- **Hugging Face token** — accept the user agreements for:
  - [pyannote/segmentation-3.0](https://hf.co/pyannote/segmentation-3.0)
  - [pyannote/speaker-diarization-3.1](https://hf.co/pyannote/speaker-diarization-3.1)
  - The Whisper model you pick (e.g. `large-v3`)

## Install

```bash
# Clone
git clone https://github.com/theUpsider/whisper-diarize.git
cd whisper-diarize

# Sync deps with uv
uv sync
```

## Environment file

Create `.env` in the repo root:

```env
HUGGINGFACE_TOKEN=hf_your_token_here
```

Get your token at https://hf.co/settings/tokens. The same token is also accepted via `--hf-token` CLI flag.

## Usage

```bash
# 1. Place MP4 files in input/
mkdir -p input
cp /path/to/videos/*.mp4 input/

# 2. Run (GPU auto-detected; uses CUDA if available)
uv run python main.py

# 3. Find results in output/
#    - final_transcript.txt  — human-readable
#    - final_transcript.json — full WhisperX result
```

### Options

| Flag             | Default    | Description                                            |
| ---------------- | ---------- | ------------------------------------------------------ |
| `--input-dir`    | `./input`  | Folder with `.mp4` files                               |
| `--work-dir`     | `./work`   | Intermediate files (merged video, WAV)                 |
| `--output-dir`   | `./output` | Final transcript files                                 |
| `--language`     | `de`       | Language code for transcription                        |
| `--model`        | `large-v3` | Whisper model name                                     |
| `--batch-size`   | `8`        | Transcription batch size                               |
| `--compute-type` | `float16`  | `float16`, `float32`, or `int8`                        |
| `--device`       | _auto_     | `cuda` or `cpu` (default: CUDA if available)           |
| `--hf-token`     | _env_      | Hugging Face token (falls back to `HUGGINGFACE_TOKEN`) |
| `--min-speakers` | —          | Minimum speaker count for diarization                  |
| `--max-speakers` | —          | Maximum speaker count for diarization                  |
| `--num-speakers` | —          | Exact speaker count for diarization                    |
| `--skip-concat`  | —          | Skip concat, use existing `work/merged.wav`            |

### Example: English, exact 3 speakers, CPU only

```bash
uv run python main.py --language en --num-speakers 3 --device cpu
```

### Example: Skip concat (re-run diarization on existing audio)

```bash
uv run python main.py --skip-concat --num-speakers 4
```

## Output format

`final_transcript.txt`:

```
Source files in concatenation order:
- 2026-01-15T10:30:00+00:00 (creation_time): meeting_part1.mp4
- 2026-01-15T11:00:00+00:00 (creation_time): meeting_part2.mp4

Transcript:

[00:00:00.000 - 00:00:05.200] SPEAKER_00: Hello everyone, let's get started.
[00:00:05.200 - 00:00:12.800] SPEAKER_01: Thanks for joining the call today.
```

`final_transcript.json` — full WhisperX alignment + diarization result.

## Generate a meeting protocol (Besprechungsprotokoll)

This repository includes the **`transkript-protokoll`** skill (`.github/skills/transkript-protokoll/SKILL.md`) — a reusable agent skill that turns the final transcript into a compact, professional German meeting protocol (Markdown + PDF).

### Using the skill with Copilot

The skill is auto-discovered by GitHub Copilot agents working in this workspace. After running transcription, ask any agent:

> "Use the transkript-protokoll skill on output/final_transcript.txt to generate a protocol."

The agent will:

- Assign speakers using contextual clues
- Condense small talk and repetition
- Extract decisions, key points, open questions, and action items
- Output `.md` and `.pdf` files

### Using the skill outside this workspace

The `.github/skills/transkript-protokoll/` folder is self-contained. You can copy it into any other project's `.github/skills/` directory or post it to **Tagity** / **Touchivity** — both platforms can create a skill from this folder structure and make it available across all your workspaces.

## Project structure

```
whisper-diarize/
├── main.py                               # Entry point
├── pyproject.toml                        # uv project config + deps
├── .env                                  # HUGGINGFACE_TOKEN (gitignored)
├── .github/
│   ├── copilot-instructions.md           # Copilot agent instructions
│   └── skills/
│       └── transkript-protokoll/         # Agent skill: transcript → protocol
│           ├── SKILL.md                  # Skill definition
│           ├── agents/                   # Agent config
│           ├── assets/
│           │   └── protokoll-vorlage.md  # Protocol template
│           └── references/
│               ├── agent-prompt.md       # Standalone agent prompt
│               └── team-sprecherzuordnung.md  # Team speaker mapping
├── input/                                # Drop .mp4 files here
├── work/                                 # Intermediate (merged.mp4, merged.wav)
└── output/                               # final_transcript.txt + .json
```
