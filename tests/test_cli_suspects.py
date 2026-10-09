"""Heuristics that point at passages worth a second look, without the audio."""

from transcriber_cli.suspects import (
    corrected_segments, low_confidence_words, repetition_windows,
)


def seg(order, start, end, text, **kw):
    return {"order": order, "start_time": start, "end_time": end, "text": text, **kw}


def test_three_consecutive_segments_with_the_same_sentence_make_one_window():
    segments = [
        seg(4, 0, 2, "Bom dia."),
        seg(5, 10, 12, "Obrigado."),
        seg(6, 12, 14, "Obrigado."),
        seg(7, 14, 16, "Obrigado."),
        seg(8, 20, 22, "Fim."),
    ]

    assert repetition_windows(segments) == [
        {"start": 10, "end": 16, "first_order": 5, "last_order": 7, "text": "obrigado", "count": 3},
    ]


def test_a_run_inside_one_segment_is_a_window():
    windows = repetition_windows([seg(0, 5, 9, "Obrigado. Obrigado. Obrigado.")])

    assert len(windows) == 1
    assert (windows[0]["count"], windows[0]["first_order"], windows[0]["last_order"]) == (3, 0, 0)


def test_two_repeats_are_below_the_default_run_length():
    segments = [seg(0, 0, 1, "Obrigado."), seg(1, 1, 2, "Obrigado."), seg(2, 2, 3, "Tchau.")]

    assert repetition_windows(segments) == []
    assert len(repetition_windows(segments, min_run=2)) == 1


def test_case_and_punctuation_do_not_break_a_run():
    segments = [seg(0, 0, 1, "obrigado!"), seg(1, 1, 2, "Obrigado."), seg(2, 2, 3, "OBRIGADO...")]

    assert len(repetition_windows(segments)) == 1


def test_low_confidence_words_carry_the_containing_segment_order():
    segments = [seg(0, 0, 10, "a"), seg(1, 10, 20, "b")]
    words = [
        {"start": 12.0, "end": 12.4, "text": " Galo", "confidence": 0.31},
        {"start": 13.0, "end": 13.4, "text": " ok", "confidence": 0.95},
        {"start": 14.0, "end": 14.4, "text": " sem", "confidence": None},
        {"start": 30.0, "end": 30.4, "text": " fora", "confidence": 0.1},
    ]

    found = low_confidence_words(words, segments)

    assert [(w["text"], w["segment_order"]) for w in found] == [(" Galo", 1), (" fora", None)]


def test_corrected_segments_are_those_with_corrections():
    fixed = seg(1, 0, 1, "Garrah", corrections=[{"heard": "Galo", "term": "Garrah", "rule": "similar"}])
    segments = [seg(0, 0, 1, "x", corrections=[]), fixed, seg(2, 1, 2, "y")]

    assert corrected_segments(segments) == [fixed]
