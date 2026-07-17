"""Tests for main.transcribe_and_diarize — diarize toggle behavior."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from main import TranscriptionConfig, transcribe_and_diarize


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
