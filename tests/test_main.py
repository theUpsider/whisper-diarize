"""Tests for main.transcribe_and_diarize — diarize toggle behavior."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from main import (
    TranscriptionConfig,
    render_srt,
    render_vtt,
    transcribe_and_diarize,
    write_outputs,
)


def _make_fake_whisperx(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Install a fake `whisperx` + `whisperx.diarize` module and return the mock."""
    fake_model = mock.MagicMock()
    fake_model.transcribe.return_value = {"segments": [], "language": "en"}

    whisperx_mod = types.ModuleType("whisperx")
    whisperx_mod.load_model = mock.MagicMock(return_value=fake_model)  # type: ignore[attr-defined]
    whisperx_mod.load_audio = mock.MagicMock(return_value="fake_audio")  # type: ignore[attr-defined]
    whisperx_mod.load_align_model = mock.MagicMock(  # type: ignore[attr-defined]
        return_value=(mock.MagicMock(), {}))
    whisperx_mod.align = mock.MagicMock(  # type: ignore[attr-defined]
        return_value={"segments": [], "aligned": True})

    diarize_mod = types.ModuleType("whisperx.diarize")
    diarize_pipeline_cls = mock.MagicMock()
    diarize_pipeline_cls.return_value.return_value = mock.MagicMock()
    diarize_mod.DiarizationPipeline = diarize_pipeline_cls  # type: ignore[attr-defined]
    diarize_mod.assign_word_speakers = mock.MagicMock(  # type: ignore[attr-defined]
        return_value={"segments": [], "speakers": True})

    monkeypatch.setitem(sys.modules, "whisperx", whisperx_mod)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", diarize_mod)
    monkeypatch.setattr(
        "main.choose_device", lambda explicit: explicit or "cpu")
    return diarize_pipeline_cls


class TestDiarizeToggle:
    """transcribe_and_diarize should honor config.diarize."""

    def test_diarize_false_skips_pipeline_and_hf_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diarize_cls = _make_fake_whisperx(monkeypatch)
        config = TranscriptionConfig(hf_token=None, diarize=False)

        result = transcribe_and_diarize(Path("fake.wav"), config=config)

        diarize_cls.assert_not_called()
        assert result == {"segments": [], "aligned": True}

    def test_diarize_true_requires_hf_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_fake_whisperx(monkeypatch)
        config = TranscriptionConfig(hf_token=None, diarize=True)

        with pytest.raises(SystemExit):
            transcribe_and_diarize(Path("fake.wav"), config=config)

    def test_diarize_true_calls_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diarize_cls = _make_fake_whisperx(monkeypatch)
        config = TranscriptionConfig(hf_token="hf_test", diarize=True)

        result = transcribe_and_diarize(Path("fake.wav"), config=config)

        diarize_cls.assert_called_once_with(token="hf_test", device="cpu")
        assert result == {"segments": [], "speakers": True}


_SAMPLE_RESULT = {
    "segments": [
        {"start": 0.0, "end": 1.5, "text": " Hello there. ", "speaker": "SPEAKER_00"},
        {"start": 1.5, "end": 3.25, "text": "General Kenobi.", "speaker": "SPEAKER_01"},
        {"start": 5.0, "end": 5.0, "text": "   ", "speaker": "SPEAKER_00"},
        {"start": 6.0, "end": 7.0, "text": "No speaker key."},
    ]
}


class TestRenderSrt:
    """render_srt should produce valid SRT blocks."""

    def test_formats_timestamps_and_index(self) -> None:
        srt = render_srt(_SAMPLE_RESULT)
        assert "1\n00:00:00,000 --> 00:00:01,500\n[SPEAKER_00]: Hello there.\n" in srt
        assert "2\n00:00:01,500 --> 00:00:03,250\n[SPEAKER_01]: General Kenobi.\n" in srt

    def test_skips_blank_text(self) -> None:
        srt = render_srt(_SAMPLE_RESULT)
        # 4 segments, 1 blank -> 3 blocks -> index goes 1, 2, 3 (no gap for the blank one)
        assert "3\n00:00:06,000 --> 00:00:07,000\nNo speaker key.\n" in srt
        assert "5.0" not in srt

    def test_omits_speaker_prefix_when_missing(self) -> None:
        srt = render_srt(_SAMPLE_RESULT)
        assert "00:00:06,000 --> 00:00:07,000\nNo speaker key.\n" in srt

    def test_empty_segments(self) -> None:
        assert render_srt({"segments": []}) == ""


class TestRenderVtt:
    """render_vtt should produce a valid WEBVTT document."""

    def test_starts_with_webvtt_header(self) -> None:
        vtt = render_vtt(_SAMPLE_RESULT)
        assert vtt.startswith("WEBVTT\n")

    def test_formats_timestamps_with_dot(self) -> None:
        vtt = render_vtt(_SAMPLE_RESULT)
        assert "00:00:00.000 --> 00:00:01.500\n[SPEAKER_00]: Hello there.\n" in vtt

    def test_skips_blank_text(self) -> None:
        vtt = render_vtt(_SAMPLE_RESULT)
        assert "     " not in vtt

    def test_empty_segments(self) -> None:
        assert render_vtt({"segments": []}) == "WEBVTT\n\n"


class TestWriteOutputs:
    """write_outputs should also emit .srt and .vtt files."""

    def test_writes_all_four_files(self, temp_dir: Path) -> None:
        transcript_path, json_path = write_outputs(
            _SAMPLE_RESULT, "sample transcript\n", temp_dir)

        srt_path = temp_dir / "final_transcript.srt"
        vtt_path = temp_dir / "final_transcript.vtt"

        assert transcript_path.exists()
        assert json_path.exists()
        assert srt_path.exists()
        assert vtt_path.exists()

        assert json.loads(json_path.read_text(encoding="utf-8")) == _SAMPLE_RESULT
        assert srt_path.read_text(encoding="utf-8").startswith("1\n")
        assert vtt_path.read_text(encoding="utf-8").startswith("WEBVTT\n")
