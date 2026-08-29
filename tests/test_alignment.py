"""Tests for optional CTC forced alignment engine and pipeline integration."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
import torch

from engines import Aligner, Word, align_words, alignment_engine_status, make_aligner
from engines.alignment import (
    MMSCTCAligner,
    normalize_token_text,
)

SAMPLE_RATE = 16000


def test_aligner_satisfies_port():
    aligner = make_aligner()
    assert isinstance(aligner, Aligner)


def test_alignment_engine_status():
    status = alignment_engine_status()
    assert "available" in status
    assert status["engine"] == "mms-fa"
    assert "pt-BR" in status["description"]


def test_normalize_token_text_portuguese_accents_and_punctuation():
    # Dictionary mockup mimicking MMS_FA character dictionary
    dictionary = {
        "-": 0, "a": 1, "i": 2, "e": 3, "n": 4, "o": 5, "u": 6, "t": 7, "s": 8, "r": 9,
        "m": 10, "k": 11, "l": 12, "d": 13, "g": 14, "h": 15, "y": 16, "b": 17, "p": 18,
        "w": 19, "c": 20, "v": 21, "j": 22, "z": 23, "f": 24, "'": 25, "q": 26, "x": 27,
    }

    # Accented Portuguese words
    tokens_ola = normalize_token_text(" Olá,", dictionary)
    assert tokens_ola == [dictionary["o"], dictionary["l"], dictionary["a"]]

    tokens_radio = normalize_token_text(" Rádio", dictionary)
    assert tokens_radio == [dictionary["r"], dictionary["a"], dictionary["d"], dictionary["i"], dictionary["o"]]

    tokens_univ = normalize_token_text(" Universitária FM.", dictionary)
    expected_chars = "universitariafm"
    assert tokens_univ == [dictionary[c] for c in expected_chars]

    # Non-dictionary characters / punctuation only
    tokens_symbols = normalize_token_text(" ...!?", dictionary)
    assert tokens_symbols == []


def test_alignment_preserves_word_text_casing_and_order(tmp_path):
    """Alignment updates timestamps without modifying text, casing, punctuation, or order."""
    audio_path = tmp_path / "test.wav"
    sf.write(audio_path, np.zeros(SAMPLE_RATE * 3, dtype=np.float32), SAMPLE_RATE)

    original_words = [
        Word(start=0.0, end=1.0, text=" Olá,", confidence=0.8),
        Word(start=1.0, end=2.0, text=" mundo!", confidence=0.85),
        Word(start=2.0, end=3.0, text=" Rádio FM.", confidence=0.9),
    ]

    aligner = MMSCTCAligner()

    # Mock model and aligner execution
    mock_model = MagicMock()
    mock_emission = torch.zeros(1, 50, 29)
    mock_model.return_value = (mock_emission, None)

    # 3 alignable words with token spans
    mock_span1 = [SimpleNamespace(start=2, end=8, score=0.95)]
    mock_span2 = [SimpleNamespace(start=12, end=20, score=0.92)]
    mock_span3 = [SimpleNamespace(start=24, end=35, score=0.98)]
    mock_aligner_fn = MagicMock(return_value=[mock_span1, mock_span2, mock_span3])

    with patch.object(MMSCTCAligner, "get_model_and_aligner", return_value=(
        mock_model,
        mock_aligner_fn,
        {"a": 1, "i": 2, "e": 3, "n": 4, "o": 5, "u": 6, "t": 7, "s": 8, "r": 9, "m": 10, "l": 12, "d": 13, "f": 24},
        torch.device("cpu"),
    )):
        refined_words = aligner.align(str(audio_path), original_words)

    assert len(refined_words) == len(original_words)
    # Exact text preservation
    assert [w.text for w in refined_words] == [w.text for w in original_words]
    # Exact order
    assert [w.text for w in refined_words] == [" Olá,", " mundo!", " Rádio FM."]
    # Start and end timestamps are monotonic and non-negative
    for w in refined_words:
        assert w.start >= 0.0
        assert w.end >= w.start


def test_alignment_fallback_on_audio_load_failure():
    """If audio cannot be read, falls back to original words without failing."""
    original_words = [
        Word(start=0.5, end=1.2, text=" Olá", confidence=0.9),
        Word(start=1.2, end=2.0, text=" mundo", confidence=0.9),
    ]

    result = align_words("non_existent_audio_path_123.wav", original_words)
    assert result == original_words


def test_alignment_fallback_on_model_exception(tmp_path):
    """If model inference or CTC alignment throws an exception, falls back to original words."""
    audio_path = tmp_path / "test.wav"
    sf.write(audio_path, np.zeros(SAMPLE_RATE * 2, dtype=np.float32), SAMPLE_RATE)

    original_words = [
        Word(start=0.0, end=1.0, text=" Teste", confidence=0.88),
    ]

    aligner = MMSCTCAligner()
    with patch.object(MMSCTCAligner, "get_model_and_aligner", side_effect=RuntimeError("CUDA OOM")):
        result = aligner.align(str(audio_path), original_words)

    assert result == original_words


def test_alignment_handles_empty_words():
    assert align_words("some_path.wav", []) == []


def test_window_splitting_and_padding():
    """Windows are split on pauses and duration limits."""
    words = [
        Word(start=0.0, end=1.0, text=" Um"),
        Word(start=1.1, end=2.0, text=" Dois"),
        # Big pause: 2.0 to 4.0s (2.0s gap > 0.8s threshold)
        Word(start=4.0, end=5.0, text=" Três"),
    ]

    aligner = MMSCTCAligner()
    windows = aligner._build_windows(words, total_duration=10.0)

    assert len(windows) == 2
    # First window covers words 0 and 1
    assert windows[0][0] == 0
    assert windows[0][1] == 2
    # Second window covers word 2
    assert windows[1][0] == 2
    assert windows[1][1] == 3


def test_monotonicity_enforcement():
    """Timestamps must not regress or have end < start."""
    words = [
        Word(start=2.0, end=1.5, text=" A"),  # end < start
        Word(start=1.0, end=3.0, text=" B"),  # start < prev start
        Word(start=4.0, end=5.0, text=" C"),
    ]

    aligner = MMSCTCAligner()
    adjusted = aligner._enforce_monotonicity(words, total_duration=10.0)

    assert len(adjusted) == 3
    assert adjusted[0].start == 2.0
    assert adjusted[0].end == 2.0  # clamped to start
    assert adjusted[1].start == 2.0  # adjusted to not regress before 2.0
    assert adjusted[1].end == 3.0
    assert adjusted[2].start == 4.0
    assert adjusted[2].end == 5.0
