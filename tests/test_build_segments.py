"""Segments are derived, not transcribed.

These tests are the reason the pipeline's currency is the Word. Ask a Transcriber for
sentences and an interruption is unattributable; ask it for Words and it falls out.
"""

from engines import Turn, Word
from tasks.shared import build_segments, turns_from_stored, words_from_stored

from .fakes import spoken


def test_interruption_mid_sentence_lands_on_its_own_line():
    """The case that segment-level alignment could not get right.

    One sentence, two speakers. Whisper would have emitted this as a single segment,
    and the old aligner would have given the whole thing to whoever overlapped it most —
    swallowing the interruption. In Words, the speaker change is just another break.
    """
    words = [
        spoken("I", 0.0, 0.3), spoken("think", 0.3, 0.7),
        spoken("we", 0.7, 1.0), spoken("should", 1.0, 1.4),
        spoken("no", 1.5, 1.8), spoken("way", 1.8, 2.1),
        spoken("ship", 2.2, 2.6), spoken("it", 2.6, 3.0),
    ]
    turns = [
        Turn(start=0.0, end=1.4, speaker="SPEAKER_00"),
        Turn(start=1.5, end=2.1, speaker="SPEAKER_01"),
        Turn(start=2.2, end=3.0, speaker="SPEAKER_00"),
    ]

    segments = build_segments(words, turns)

    assert [(s["speaker"], s["text"]) for s in segments] == [
        ("SPEAKER_00", "I think we should"),
        ("SPEAKER_01", "no way"),
        ("SPEAKER_00", "ship it"),
    ]


def test_segment_ends_at_a_sentence():
    words = [
        spoken("Right.", 0.0, 0.5),
        spoken("Next", 0.6, 1.0), spoken("item.", 1.0, 1.5),
    ]
    turns = [Turn(start=0.0, end=1.5, speaker="SPEAKER_00")]

    assert [s["text"] for s in build_segments(words, turns)] == ["Right.", "Next item."]


def test_segment_ends_at_a_long_pause():
    words = [spoken("Hello", 0.0, 0.5), spoken("again", 4.0, 4.5)]
    turns = [Turn(start=0.0, end=5.0, speaker="SPEAKER_00")]

    segments = build_segments(words, turns)

    assert [s["text"] for s in segments] == ["Hello", "again"]
    assert segments[0]["end"] == 0.5
    assert segments[1]["start"] == 4.0


def test_a_segment_does_not_run_on_forever():
    """A speaker who never pauses and never lands on a full stop still gets paragraphs."""
    words = [spoken(f"word{i}", float(i), float(i) + 0.5) for i in range(40)]
    turns = [Turn(start=0.0, end=40.0, speaker="SPEAKER_00")]

    segments = build_segments(words, turns)

    assert len(segments) > 1
    assert all(s["end"] - s["start"] <= 31.0 for s in segments)


def test_punctuation_glues_and_words_do_not_run_together():
    words = [spoken("Rádio", 0.0, 0.4), Word(start=0.4, end=0.5, text=","), spoken("sim", 0.5, 0.8)]
    turns = [Turn(start=0.0, end=1.0, speaker="SPEAKER_00")]

    assert build_segments(words, turns)[0]["text"] == "Rádio, sim"


def test_a_word_in_a_diarization_hole_goes_to_the_nearest_speaker():
    """Diarization leaves small gaps. A word in one still belongs to somebody."""
    words = [spoken("and", 2.05, 2.15)]
    turns = [
        Turn(start=0.0, end=2.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=4.0, speaker="SPEAKER_01"),
    ]

    assert build_segments(words, turns)[0]["speaker"] == "SPEAKER_00"


def test_words_with_no_diarization_at_all_are_unknown():
    assert build_segments([spoken("hello", 0.0, 0.5)], [])[0]["speaker"] == "UNKNOWN"


def test_segment_confidence_is_the_mean_of_its_words():
    words = [spoken("a", 0.0, 0.1, 0.9), spoken("b", 0.1, 0.2, 0.5), spoken("c", 0.2, 0.3, None)]
    turns = [Turn(start=0.0, end=1.0, speaker="SPEAKER_00")]

    assert build_segments(words, turns)[0]["confidence"] == 0.7


def test_no_words_no_segments():
    assert build_segments([], [Turn(start=0.0, end=1.0, speaker="SPEAKER_00")]) == []


def test_words_from_a_meeting_transcribed_before_the_port():
    """Old Meetings stored whisper's coarse segments as a bare list. They still read."""
    raw = [{"start": 0.0, "end": 2.0, "text": "Olá pessoal.", "confidence": 0.8}]

    words = words_from_stored(raw)

    assert words == [Word(start=0.0, end=2.0, text=" Olá pessoal.", confidence=0.8)]


def test_words_from_a_meeting_transcribed_after_the_port():
    raw = {
        "engine": "parakeet.cpp",
        "preset": "parakeet-tdt-0.6b-v3",
        "words": [{"start": 0.0, "end": 0.4, "text": " Olá", "confidence": 0.99}],
    }

    assert words_from_stored(raw) == [Word(start=0.0, end=0.4, text=" Olá", confidence=0.99)]


def test_turns_read_from_either_era():
    legacy = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    current = {"engine": "pyannote", "turns": legacy}

    expected = [Turn(start=0.0, end=1.0, speaker="SPEAKER_00")]
    assert turns_from_stored(legacy) == expected
    assert turns_from_stored(current) == expected
    assert turns_from_stored(None) == []
