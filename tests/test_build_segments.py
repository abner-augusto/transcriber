"""Segments are derived, not transcribed.

These tests are the reason the pipeline's currency is the Word. Ask a Transcriber for
sentences and an interruption is unattributable; ask it for Words and it falls out.
"""

from engines import Turn, Word, compute_overlaps
from tasks.shared import (
    SPEAKER_SWITCH_PENALTY,
    attribution_turns_from_stored,
    build_segments,
    exclusive_turns_from_stored,
    overlaps_from_stored,
    smooth_word_speakers,
    turns_from_stored,
    words_from_stored,
)

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


def test_word_alignment_score_round_trips_and_is_optional():
    aligned = Word(
        start=0.0,
        end=0.4,
        text=" Olá",
        confidence=0.99,
        alignment_score=0.72,
    )

    assert Word.from_dict(aligned.to_dict()) == aligned
    assert Word.from_dict({"start": 0.0, "end": 0.4, "text": " Olá"}).alignment_score is None


def test_turns_read_from_either_era():
    legacy = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    current = {"engine": "pyannote", "turns": legacy}

    expected = [Turn(start=0.0, end=1.0, speaker="SPEAKER_00")]
    assert turns_from_stored(legacy) == expected
    assert turns_from_stored(current) == expected
    assert turns_from_stored(None) == []


def test_exclusive_turns_and_overlaps_read_from_stored():
    raw_with_exclusive = {
        "engine": "pyannote",
        "turns": [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 5.0, "speaker": "SPEAKER_01"},
        ],
        "exclusive_turns": [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 3.0, "end": 5.0, "speaker": "SPEAKER_01"},
        ],
        "overlaps": [
            {"start": 2.0, "end": 3.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
        ],
    }

    assert exclusive_turns_from_stored(raw_with_exclusive) == [
        Turn(start=0.0, end=2.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=5.0, speaker="SPEAKER_01"),
    ]
    assert attribution_turns_from_stored(raw_with_exclusive) == [
        Turn(start=0.0, end=2.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=5.0, speaker="SPEAKER_01"),
    ]
    assert overlaps_from_stored(raw_with_exclusive) == [
        {"start": 2.0, "end": 3.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
    ]

    raw_without_exclusive = {
        "engine": "pyannote",
        "turns": [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 5.0, "speaker": "SPEAKER_01"},
        ],
    }
    assert exclusive_turns_from_stored(raw_without_exclusive) is None
    assert attribution_turns_from_stored(raw_without_exclusive) == [
        Turn(start=0.0, end=3.0, speaker="SPEAKER_00"),
        Turn(start=2.0, end=5.0, speaker="SPEAKER_01"),
    ]
    # Computes overlaps dynamically from turns
    assert overlaps_from_stored(raw_without_exclusive) == [
        {"start": 2.0, "end": 3.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
    ]


def test_compute_overlaps_empty_and_disjoint():
    assert compute_overlaps([]) == []
    assert compute_overlaps([Turn(start=0.0, end=1.0, speaker="SPEAKER_00")]) == []
    assert compute_overlaps([
        Turn(start=0.0, end=1.0, speaker="SPEAKER_00"),
        Turn(start=1.5, end=2.5, speaker="SPEAKER_01"),
    ]) == []


def test_compute_overlaps_multiple_overlapping_speakers_and_merging():
    # Speaker 0: 0.0 - 5.0
    # Speaker 1: 2.0 - 4.0
    # Speaker 2: 3.0 - 6.0
    turns = [
        Turn(start=0.0, end=5.0, speaker="SPEAKER_00"),
        Turn(start=2.0, end=4.0, speaker="SPEAKER_01"),
        Turn(start=3.0, end=6.0, speaker="SPEAKER_02"),
    ]
    overlaps = compute_overlaps(turns)
    assert overlaps == [
        {"start": 2.0, "end": 3.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
        {"start": 3.0, "end": 4.0, "speakers": ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]},
        {"start": 4.0, "end": 5.0, "speakers": ["SPEAKER_00", "SPEAKER_02"]},
    ]


def test_strictly_greater_overlap_wins_regardless_of_turn_order():
    word = spoken("overlap", 1.0, 2.0)
    # Turn 0 overlaps 0.4s (1.0 to 1.4); Turn 1 overlaps 0.6s (1.4 to 2.0)
    turn_smaller = Turn(start=0.0, end=1.4, speaker="SPEAKER_00")
    turn_larger = Turn(start=1.4, end=3.0, speaker="SPEAKER_01")

    res1 = build_segments([word], [turn_smaller, turn_larger])
    res2 = build_segments([word], [turn_larger, turn_smaller])

    assert res1[0]["speaker"] == "SPEAKER_01"
    assert res2[0]["speaker"] == "SPEAKER_01"


def test_equal_overlap_tie_breaking_deterministic_and_order_independent():
    # Word from 0.4 to 1.6
    # Turn A (0.0 to 1.0) overlaps 0.6s (0.4 to 1.0)
    # Turn B (1.0 to 2.0) overlaps 0.6s (1.0 to 1.6)
    word = spoken("tie", 0.4, 1.6)
    turn_a = Turn(start=0.0, end=1.0, speaker="SPEAKER_00")
    turn_b = Turn(start=1.0, end=2.0, speaker="SPEAKER_01")

    res_forward = build_segments([word], [turn_a, turn_b])
    res_reverse = build_segments([word], [turn_b, turn_a])

    # Both must resolve to the same speaker deterministically (earlier start time SPEAKER_00)
    assert res_forward[0]["speaker"] == "SPEAKER_00"
    assert res_reverse[0]["speaker"] == "SPEAKER_00"


def test_equal_overlap_identical_bounds_tie_breaks_by_speaker():
    # Two turns with identical start and end times overlapping the word
    word = spoken("simultaneous", 0.2, 0.8)
    turn_0 = Turn(start=0.0, end=1.0, speaker="SPEAKER_00")
    turn_1 = Turn(start=0.0, end=1.0, speaker="SPEAKER_01")

    res1 = build_segments([word], [turn_0, turn_1])
    res2 = build_segments([word], [turn_1, turn_0])

    assert res1[0]["speaker"] == "SPEAKER_00"
    assert res2[0]["speaker"] == "SPEAKER_00"


def test_diarization_gap_nearest_speaker_regardless_of_turn_order():
    # Word at 2.1 to 2.2. Turn 0 ends at 2.0 (gap 0.1s), Turn 1 starts at 2.5 (gap 0.3s)
    word = spoken("gap", 2.1, 2.2)
    turn_closer = Turn(start=0.0, end=2.0, speaker="SPEAKER_00")
    turn_farther = Turn(start=2.5, end=4.0, speaker="SPEAKER_01")

    res1 = build_segments([word], [turn_closer, turn_farther])
    res2 = build_segments([word], [turn_farther, turn_closer])

    assert res1[0]["speaker"] == "SPEAKER_00"
    assert res2[0]["speaker"] == "SPEAKER_00"


def test_diarization_gap_equidistant_tie_breaking_deterministic_and_order_independent():
    # Word from 2.0 to 3.0. Turn A ends at 1.0 (gap 1.0s). Turn B starts at 4.0 (gap 1.0s).
    word = spoken("middle", 2.0, 3.0)
    turn_a = Turn(start=0.0, end=1.0, speaker="SPEAKER_00")
    turn_b = Turn(start=4.0, end=5.0, speaker="SPEAKER_01")

    res1 = build_segments([word], [turn_a, turn_b])
    res2 = build_segments([word], [turn_b, turn_a])

    assert res1[0]["speaker"] == "SPEAKER_00"
    assert res2[0]["speaker"] == "SPEAKER_00"


def test_diarization_gap_exceeding_tolerance_is_unknown():
    # Word at 10.0 to 10.5. Turn ends at 5.0 (gap 5.0s > 2.0s tolerance)
    word = spoken("far", 10.0, 10.5)
    turn = Turn(start=0.0, end=5.0, speaker="SPEAKER_00")

    res = build_segments([word], [turn])
    assert res[0]["speaker"] == "UNKNOWN"


def test_turn_index_keeps_long_turns_that_start_before_the_search_window():
    word = spoken("inside", 100.0, 100.5)
    turns = [
        Turn(start=0.0, end=101.0, speaker="SPEAKER_00"),
        Turn(start=99.0, end=99.2, speaker="SPEAKER_01"),
    ]

    assert build_segments([word], turns)[0]["speaker"] == "SPEAKER_00"


def test_turn_index_excludes_turns_beyond_the_tolerance_window():
    word = spoken("alone", 0.0, 0.5)
    turns = [Turn(start=2.6, end=3.0, speaker="SPEAKER_00")]

    assert build_segments([word], turns)[0]["speaker"] == "UNKNOWN"


def test_dp_transition_tie_uses_previous_turn_evidence_not_candidate_order():
    words = [spoken("first", 1.0, 2.0), spoken("later", 5.0, 6.0)]
    turns = [
        Turn(start=1.0, end=1.5, speaker="SPEAKER_00"),
        Turn(start=0.5, end=1.5, speaker="SPEAKER_01"),
        Turn(start=5.0, end=6.0, speaker="SPEAKER_02"),
    ]

    assert smooth_word_speakers(words, turns) == ["SPEAKER_01", "SPEAKER_02"]


def test_isolated_one_word_flap_is_smoothed_to_surrounding_speaker():
    """Single-word timestamp flap / glitch is smoothed back into surrounding turn."""
    words = [
        spoken("I", 0.0, 0.4),
        spoken("really", 0.4, 0.8),
        spoken("hope", 0.8, 1.2),     # Isolated flap overlapping SPEAKER_01
        spoken("this", 1.2, 1.6),
        spoken("works", 1.6, 2.0),
    ]
    turns = [
        Turn(start=0.0, end=0.8, speaker="SPEAKER_00"),
        Turn(start=0.8, end=1.2, speaker="SPEAKER_01"),
        Turn(start=1.2, end=2.0, speaker="SPEAKER_00"),
    ]

    segments = build_segments(words, turns)
    assert len(segments) == 1
    assert segments[0]["speaker"] == "SPEAKER_00"
    assert segments[0]["text"] == "I really hope this works"

    speakers = smooth_word_speakers(words, turns)
    assert speakers == ["SPEAKER_00"] * 5


def test_sustained_multi_word_interruption_is_preserved_and_breaks_segment():
    """Multi-word interruption overcomes the switch penalty and creates a separate segment."""
    words = [
        spoken("I", 0.0, 0.4),
        spoken("think", 0.4, 0.8),
        spoken("wait", 0.8, 1.2),      # SPEAKER_01 word 1
        spoken("no", 1.2, 1.6),        # SPEAKER_01 word 2
        spoken("actually", 1.6, 2.0),  # SPEAKER_00 resumes
        spoken("yes", 2.0, 2.4),
    ]
    turns = [
        Turn(start=0.0, end=0.8, speaker="SPEAKER_00"),
        Turn(start=0.8, end=1.6, speaker="SPEAKER_01"),
        Turn(start=1.6, end=2.4, speaker="SPEAKER_00"),
    ]

    segments = build_segments(words, turns)
    assert len(segments) == 3
    assert [(s["speaker"], s["text"]) for s in segments] == [
        ("SPEAKER_00", "I think"),
        ("SPEAKER_01", "wait no"),
        ("SPEAKER_00", "actually yes"),
    ]

    speakers = smooth_word_speakers(words, turns)
    assert speakers == [
        "SPEAKER_00", "SPEAKER_00",
        "SPEAKER_01", "SPEAKER_01",
        "SPEAKER_00", "SPEAKER_00",
    ]


def test_inter_word_gap_exceeding_pause_threshold_waives_switch_penalty():
    """Pause > MAX_PAUSE_SECONDS waives the switch penalty so even 1 word can switch speaker cleanly."""
    words = [
        spoken("Hello", 0.0, 0.5),     # SPEAKER_00
        spoken("Yes", 2.5, 3.0),       # Gap = 2.0s > 1.0s -> SPEAKER_01 (1 word!)
        spoken("Continue", 5.0, 5.5),  # Gap = 2.0s > 1.0s -> SPEAKER_00
    ]
    turns = [
        Turn(start=0.0, end=0.5, speaker="SPEAKER_00"),
        Turn(start=2.5, end=3.0, speaker="SPEAKER_01"),
        Turn(start=5.0, end=5.5, speaker="SPEAKER_00"),
    ]

    segments = build_segments(words, turns)
    assert len(segments) == 3
    assert [(s["speaker"], s["text"]) for s in segments] == [
        ("SPEAKER_00", "Hello"),
        ("SPEAKER_01", "Yes"),
        ("SPEAKER_00", "Continue"),
    ]


def test_switch_penalty_tunability():
    """With switch_penalty=0.0, isolated single-word flaps are not smoothed."""
    words = [
        spoken("I", 0.0, 0.4),
        spoken("really", 0.4, 0.8),
        spoken("hope", 0.8, 1.2),
        spoken("this", 1.2, 1.6),
        spoken("works", 1.6, 2.0),
    ]
    turns = [
        Turn(start=0.0, end=0.8, speaker="SPEAKER_00"),
        Turn(start=0.8, end=1.2, speaker="SPEAKER_01"),
        Turn(start=1.2, end=2.0, speaker="SPEAKER_00"),
    ]

    # Without switch penalty, flap is assigned to SPEAKER_01
    unsmoothed = smooth_word_speakers(words, turns, switch_penalty=0.0)
    assert unsmoothed == [
        "SPEAKER_00", "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_00", "SPEAKER_00",
    ]

    # With default switch penalty, flap is smoothed
    smoothed = smooth_word_speakers(words, turns, switch_penalty=SPEAKER_SWITCH_PENALTY)
    assert smoothed == ["SPEAKER_00"] * 5


def test_low_alignment_score_weakens_timestamp_evidence():
    turns = [
        Turn(start=0.0, end=1.0, speaker="SPEAKER_00"),
        Turn(start=1.0, end=2.0, speaker="SPEAKER_01"),
        Turn(start=2.0, end=3.0, speaker="SPEAKER_00"),
    ]
    reliable = [
        spoken("I", 0.0, 1.0),
        spoken("object", 1.0, 2.0),
        spoken("again", 2.0, 3.0),
    ]
    uncertain = [
        reliable[0],
        Word(start=1.0, end=2.0, text=" object", alignment_score=0.1),
        reliable[2],
    ]

    assert smooth_word_speakers(reliable, turns, switch_penalty=0.3) == [
        "SPEAKER_00", "SPEAKER_01", "SPEAKER_00",
    ]
    assert smooth_word_speakers(uncertain, turns, switch_penalty=0.3) == [
        "SPEAKER_00", "SPEAKER_00", "SPEAKER_00",
    ]


def test_smoothing_empty_input_and_edge_cases():
    """Empty words or turns are handled gracefully."""
    turn = Turn(start=0.0, end=1.0, speaker="SPEAKER_00")
    word = spoken("hello", 0.0, 0.5)

    assert smooth_word_speakers([], [turn]) == []
    assert smooth_word_speakers([word], []) == ["UNKNOWN"]
    assert smooth_word_speakers([], []) == []


