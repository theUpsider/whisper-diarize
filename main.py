from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

load_dotenv()


SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_DIR = SCRIPT_DIR / "input"
INPUT_PROCESSED_DIR = SCRIPT_DIR / "input_processed"
WORK_DIR = SCRIPT_DIR / "work"
OUTPUT_DIR = SCRIPT_DIR / "output"


@dataclass(frozen=True)
class OrderedVideo:
    path: Path
    order_time: datetime
    order_source: str


@dataclass
class TranscriptionConfig:
    """Parameters for transcribe_and_diarize — usable without argparse."""

    hf_token: str | None = None
    model: str = "large-v3"
    device: str | None = None
    compute_type: str = "float16"
    language: str = "de"
    batch_size: int = 8
    min_speakers: int | None = None
    max_speakers: int | None = None
    num_speakers: int | None = None
    diarize: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Concatenate MP4 files from input/, ordered by creation date, then "
            "transcribe and diarize the result with WhisperX."
        )
    )
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--language", default="de")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--hf-token", default=os.environ.get("HUGGINGFACE_TOKEN"))
    parser.add_argument("--min-speakers", type=int, default=None)
    parser.add_argument("--max-speakers", type=int, default=None)
    parser.add_argument("--num-speakers", type=int, default=None)
    parser.add_argument(
        "--no-diarize", dest="diarize", action="store_false", default=True,
        help="Skip speaker diarization (no HF token required)")
    parser.add_argument("--skip-concat", action="store_true",
                        help="Skip concat & audio extraction (use existing work/merged.wav)")
    return parser.parse_args()


def ensure_binary(name: str) -> None:
    if not shutil_which(name):
        raise SystemExit(f"Missing required binary: {name}")


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def run_command(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def ffprobe_creation_time(path: Path) -> datetime | None:
    probe = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format_tags=creation_time:stream_tags=creation_time",
            str(path),
        ],
        capture_output=True,
    )
    payload = json.loads(probe.stdout or "{}")

    candidate_values: list[str] = []
    format_tags = payload.get("format", {}).get("tags", {})
    if isinstance(format_tags, dict):
        creation_time = format_tags.get("creation_time")
        if creation_time:
            candidate_values.append(creation_time)

    for stream in payload.get("streams", []):
        tags = stream.get("tags", {})
        if not isinstance(tags, dict):
            continue
        creation_time = tags.get("creation_time")
        if creation_time:
            candidate_values.append(creation_time)

    for value in candidate_values:
        parsed = parse_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def parse_timestamp(raw: str) -> datetime | None:
    normalized = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def discover_videos(input_dir: Path) -> list[OrderedVideo]:
    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    videos: list[OrderedVideo] = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".mp4":
            continue
        creation_time = ffprobe_creation_time(path)
        if creation_time is not None:
            videos.append(OrderedVideo(
                path=path, order_time=creation_time, order_source="creation_time"))
            continue

        fallback = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc)
        videos.append(OrderedVideo(
            path=path, order_time=fallback, order_source="mtime"))

    if not videos:
        raise SystemExit(f"No MP4 files found in {input_dir}")

    return sorted(videos, key=lambda item: (item.order_time, item.path.name.lower()))


def write_concat_file(videos: list[OrderedVideo], concat_file: Path) -> None:
    lines = [
        f"file {shlex.quote(str(video.path.resolve()))}" for video in videos]
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_videos(videos: list[OrderedVideo], work_dir: Path) -> Path:
    concat_file = work_dir / "concat.txt"
    merged_video = work_dir / "merged.mp4"
    write_concat_file(videos, concat_file)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(merged_video),
        ]
    )
    return merged_video


def extract_audio(video_path: Path, work_dir: Path) -> Path:
    audio_path = work_dir / "merged.wav"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-vn",
            str(audio_path),
        ]
    )
    return audio_path


def choose_device(explicit: str | None) -> str:
    if explicit:
        return explicit
    import torch  # lazy — avoid loading CUDA at import time
    return "cuda" if torch.cuda.is_available() else "cpu"


def transcribe_and_diarize(
    audio_path: Path,
    config: TranscriptionConfig | None = None,
    args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    """Transcribe and diarize audio.

    Prefer passing ``config`` (TranscriptionConfig).  The ``args`` parameter
    is kept for backward compatibility with the CLI entry point.
    """
    if config is None and args is not None:
        config = TranscriptionConfig(
            hf_token=args.hf_token,
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            batch_size=args.batch_size,
            min_speakers=args.min_speakers,
            max_speakers=args.max_speakers,
            num_speakers=args.num_speakers,
            diarize=args.diarize,
        )
    if config is None:
        raise ValueError("Either config or args must be provided")

    if config.diarize and not config.hf_token:
        raise SystemExit(
            "Missing Hugging Face token. Set HUGGINGFACE_TOKEN or pass --hf-token."
        )

    import whisperx  # lazy — avoid loading ML stack at import time

    device = choose_device(config.device)
    model = whisperx.load_model(
        config.model,
        device,
        compute_type=config.compute_type,
        language=config.language,
    )
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(
        audio, batch_size=config.batch_size, language=config.language)

    model_a, metadata = whisperx.load_align_model(
        language_code=result["language"],
        device=device,
    )
    aligned = whisperx.align(
        result["segments"],
        model_a,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    if not config.diarize:
        return cast("dict[str, Any]", aligned)

    from whisperx.diarize import DiarizationPipeline, assign_word_speakers

    diarize_model = DiarizationPipeline(
        token=config.hf_token,
        device=device,
    )
    diarize_segments = diarize_model(
        str(audio_path),
        min_speakers=config.min_speakers,
        max_speakers=config.max_speakers,
        num_speakers=config.num_speakers,
    )
    # Unpack tuple if diarize_model returns (DataFrame, dict) in newer WhisperX
    if isinstance(diarize_segments, tuple):
        diarize_segments = diarize_segments[0]
    return cast("dict[str, Any]", assign_word_speakers(diarize_segments, aligned))


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def render_transcript(result: dict[str, Any], ordered_videos: list[OrderedVideo]) -> str:
    header_lines = [
        "Source files in concatenation order:",
        *[
            f"- {item.order_time.isoformat()} ({item.order_source}): {item.path.name}"
            for item in ordered_videos
        ],
        "",
        "Transcript:",
        "",
    ]

    body_lines: list[str] = []
    for segment in result.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        speaker = segment.get("speaker", "UNKNOWN")
        start = format_timestamp(segment.get("start"))
        end = format_timestamp(segment.get("end"))
        body_lines.append(f"[{start} - {end}] {speaker}: {text}")

    return "\n".join(header_lines + body_lines) + "\n"


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_vtt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def render_srt(result: dict[str, Any]) -> str:
    blocks: list[str] = []
    index = 1
    for segment in result.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        start = segment.get("start") or 0.0
        end = segment.get("end") or 0.0
        speaker = segment.get("speaker")
        prefix = f"[{speaker}]: " if speaker else ""
        blocks.append(
            f"{index}\n"
            f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n"
            f"{prefix}{text}\n"
        )
        index += 1
    return "\n".join(blocks) + ("\n" if blocks else "")


def render_vtt(result: dict[str, Any]) -> str:
    blocks: list[str] = ["WEBVTT\n"]
    for segment in result.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        start = segment.get("start") or 0.0
        end = segment.get("end") or 0.0
        speaker = segment.get("speaker")
        prefix = f"[{speaker}]: " if speaker else ""
        blocks.append(
            f"{_format_vtt_timestamp(start)} --> {_format_vtt_timestamp(end)}\n"
            f"{prefix}{text}\n"
        )
    return "\n".join(blocks) + "\n"


def write_outputs(
    result: dict[str, Any],
    transcript_text: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / "final_transcript.txt"
    json_path = output_dir / "final_transcript.json"
    srt_path = output_dir / "final_transcript.srt"
    vtt_path = output_dir / "final_transcript.vtt"
    transcript_path.write_text(transcript_text, encoding="utf-8")
    json_path.write_text(json.dumps(
        result, ensure_ascii=False, indent=2), encoding="utf-8")
    srt_path.write_text(render_srt(result), encoding="utf-8")
    vtt_path.write_text(render_vtt(result), encoding="utf-8")
    return transcript_path, json_path


def main() -> int:
    args = parse_args()
    ensure_binary("ffmpeg")
    ensure_binary("ffprobe")

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    run_work_dir = args.work_dir / run_ts
    run_output_dir = args.output_dir / run_ts

    run_work_dir.mkdir(parents=True, exist_ok=True)
    run_output_dir.mkdir(parents=True, exist_ok=True)
    args.input_dir.mkdir(parents=True, exist_ok=True)

    ordered_videos = discover_videos(args.input_dir)
    merged_video: Path | None = None
    if args.skip_concat:
        audio_path = run_work_dir / "merged.wav"
        if not audio_path.exists():
            raise SystemExit(f"Audio file not found: {audio_path}")
    else:
        merged_video = concat_videos(ordered_videos, run_work_dir)
        audio_path = extract_audio(merged_video, run_work_dir)
    result = transcribe_and_diarize(audio_path, args=args)
    transcript_text = render_transcript(result, ordered_videos)
    transcript_path, json_path = write_outputs(
        result, transcript_text, run_output_dir)

    # Move processed input files to input_processed/
    processed_dir = INPUT_PROCESSED_DIR
    processed_dir.mkdir(parents=True, exist_ok=True)
    for video in ordered_videos:
        dest = processed_dir / video.path.name
        video.path.rename(dest)
        print(f"Moved: {video.path.name} -> {processed_dir.name}/")

    if not args.skip_concat and merged_video is not None:
        print(f"Merged video: {merged_video}")
    print(f"Extracted audio: {audio_path}")
    print(f"Transcript text: {transcript_path}")
    print(f"Transcript JSON: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
