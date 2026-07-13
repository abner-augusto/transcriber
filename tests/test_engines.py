"""The adapters, tested at the only place they can go wrong without a GPU: parsing.

The fixtures are real output — captured from whisper-cli and parakeet-cli running on
30 seconds of test.mp3 — so these tests fail if either tool changes its format.
"""

import json
from pathlib import Path

import pytest

from engines import Diarizer, Transcriber, Turn, Word, make_transcriber
from engines.parakeet_cpp import parse_words as parse_parakeet
from engines.whisper_cpp import parse_words as parse_whisper

from .fakes import FakeDiarizer, FakeTranscriber

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_fake_satisfies_the_ports():
    """If this fails, the fakes have drifted from the ports and every test above is a lie."""
    assert isinstance(FakeTranscriber([]), Transcriber)
    assert isinstance(FakeDiarizer([]), Diarizer)


def test_whisper_subword_tokens_are_stitched_back_into_words():
    """whisper.cpp splits "Rádio" into " R" + "ád" + "io". A Word is the whole thing."""
    data = json.loads((FIXTURES / "whisper_full.json").read_text(encoding="utf-8"))

    words = parse_whisper(data)

    assert [w.text for w in words] == [
        " no", " ar", " pela", " Rádio", " Universitária", " FM,", " Sem", " Fronteiras,", " Plural",
    ]
    assert "".join(w.text for w in words).strip() == (
        "no ar pela Rádio Universitária FM, Sem Fronteiras, Plural"
    )


def test_whisper_control_tokens_never_reach_the_transcript():
    data = json.loads((FIXTURES / "whisper_full.json").read_text(encoding="utf-8"))

    words = parse_whisper(data)

    assert not any("[_" in w.text for w in words)
    assert all(w.end >= w.start for w in words)
    assert all(0.0 <= w.confidence <= 1.0 for w in words)


def test_parakeet_words_are_read_past_the_cuda_chatter():
    """parakeet-cli prints its JSON after the backend has finished talking to itself."""
    stdout = (FIXTURES / "parakeet_stdout.txt").read_text(encoding="utf-8")

    words = parse_parakeet(stdout)

    assert words[0] == Word(start=3.2, end=3.52, text=" No", confidence=0.9925)
    assert "".join(w.text for w in words).strip() == "No ar, pela Rádio Universitária FM."


def test_parakeet_without_json_is_an_error_not_an_empty_transcript():
    with pytest.raises(RuntimeError):
        parse_parakeet("ggml_cuda_init: found 1 CUDA devices\n")


def test_both_engines_agree_on_the_shape_of_a_word():
    """The port's whole promise: two Engines, one currency."""
    whisper = parse_whisper(json.loads((FIXTURES / "whisper_full.json").read_text(encoding="utf-8")))
    parakeet = parse_parakeet((FIXTURES / "parakeet_stdout.txt").read_text(encoding="utf-8"))

    for word in whisper + parakeet:
        assert isinstance(word, Word)
        assert word.text.startswith(" ")  # join-ready, per the Word contract
        assert word.end >= word.start


def test_a_preset_names_the_engine_it_runs_on():
    transcriber = make_transcriber({
        "id": "whisper-large-v3-turbo",
        "engine": "whisper.cpp",
        "model_path": "./models/ggml-large-v3-turbo.bin",
        "language": "pt",
    })

    assert isinstance(transcriber, Transcriber)
    assert transcriber.language == "pt"


def test_an_unknown_engine_fails_loudly():
    with pytest.raises(ValueError, match="Unknown transcription engine"):
        make_transcriber({"id": "x", "engine": "deepgram", "model_path": "x"})
