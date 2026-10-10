"""Heuristics that point at passages worth a second look, without the audio."""

import pytest

from transcriber_cli.suspects import (
    WEAK_WORD, corrected_segments, low_confidence_passages, repetition_windows, speaker_cuts,
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


def word(start, text, confidence):
    return {"start": start, "end": start + 0.4, "text": text, "confidence": confidence}


def test_low_confidence_passages_group_weak_words_by_segment_worst_first():
    segments = [seg(0, 0, 10, "a"), seg(1, 10, 20, "b"), seg(2, 20, 30, "c")]
    words = [
        word(1.0, " Do", 0.37),
        word(2.0, " ok", 0.95),
        word(3.0, " algo", 0.14),
        word(12.0, " Galo", 0.31),
        word(13.0, " sem", None),
        word(25.0, " forte", 0.9),
        word(40.0, " fora", 0.05),
    ]

    found = low_confidence_passages(words, segments)

    assert found == [
        {"order": 0, "worst": 0.14, "words": [(" Do", 0.37), (" algo", 0.14)]},
        {"order": 1, "worst": 0.31, "words": [(" Galo", 0.31)]},
    ]


def test_a_word_at_the_threshold_is_not_weak():
    segments = [seg(0, 0, 10, "a")]

    assert low_confidence_passages([word(1.0, " x", WEAK_WORD)], segments) == []
    assert len(low_confidence_passages([word(1.0, " x", WEAK_WORD)], segments, below=0.5)) == 1


def test_an_edited_segment_is_not_a_low_confidence_passage():
    # Word confidence describes what the Transcriber heard; an edit already replaced that text.
    segments = [seg(0, 0, 10, "Informakon", is_edited=True), seg(1, 10, 20, "Galo")]
    words = [word(1.0, " Infarmacom", 0.26), word(12.0, " Galo", 0.31)]

    assert low_confidence_passages(words, segments) == [
        {"order": 1, "worst": 0.31, "words": [(" Galo", 0.31)]},
    ]


def test_corrected_segments_are_those_with_corrections():
    fixed = seg(1, 0, 1, "Garrah", corrections=[{"heard": "Galo", "term": "Garrah", "rule": "similar"}])
    segments = [seg(0, 0, 1, "x", corrections=[]), fixed, seg(2, 1, 2, "y")]

    assert corrected_segments(segments) == [fixed]


def test_corrected_segments_skip_corrections_the_user_confirmed():
    confirmed = {"heard": "Galo", "term": "Garrah", "rule": "misheard", "confirmed": True}
    open_fix = {"heard": "Doker", "term": "Docker", "rule": "similar", "confirmed": False}
    only_confirmed = seg(0, 0, 1, "Garrah", corrections=[confirmed])
    mixed = seg(1, 1, 2, "Garrah Docker", corrections=[confirmed, open_fix])

    assert corrected_segments([only_confirmed, mixed]) == [mixed]


def test_a_sentence_that_continues_across_two_speakers_is_a_cut():
    segments = [
        seg(68, 151.0, 151.6, "É, tá", speaker_id=1),
        seg(69, 151.9, 153.0, "errado aqui, capitão.", speaker_id=2),
    ]

    assert speaker_cuts(segments) == [{"first_order": 68, "second_order": 69, "gap": 0.3}]


@pytest.mark.parametrize("ending", [".", "?", "!", "…"])
def test_a_first_segment_that_ends_a_sentence_is_not_a_cut(ending):
    segments = [
        seg(0, 0, 1, f"Pode ser{ending}", speaker_id=1),
        seg(1, 1.2, 2, "Claro", speaker_id=2),
    ]

    assert speaker_cuts(segments) == []


def test_the_same_speaker_on_both_sides_is_not_a_cut():
    segments = [seg(0, 0, 1, "É, tá", speaker_id=1), seg(1, 1.2, 2, "errado", speaker_id=1)]

    assert speaker_cuts(segments) == []


def test_a_gap_over_one_second_is_not_a_cut_and_exactly_one_second_is():
    far = [seg(0, 0, 1, "É, tá", speaker_id=1), seg(1, 2.5, 3, "errado", speaker_id=2)]
    edge = [seg(0, 0, 1, "É, tá", speaker_id=1), seg(1, 2.0, 3, "errado", speaker_id=2)]

    assert speaker_cuts(far) == []
    assert speaker_cuts(edge) == [{"first_order": 0, "second_order": 1, "gap": 1.0}]


@pytest.mark.parametrize("edited", [0, 1])
def test_a_segment_whose_speaker_a_person_set_is_not_a_cut(edited):
    segments = [seg(0, 0, 1, "É, tá", speaker_id=1), seg(1, 1.2, 2, "errado", speaker_id=2)]
    segments[edited]["speaker_edited"] = True

    assert speaker_cuts(segments) == []


def test_segments_out_of_order_are_paired_by_order():
    segments = [
        seg(1, 1.2, 2, "errado", speaker_id=2),
        seg(0, 0, 1, "É, tá", speaker_id=1),
    ]

    assert speaker_cuts(segments) == [{"first_order": 0, "second_order": 1, "gap": 0.2}]


@pytest.mark.parametrize("missing", [0, 1])
def test_a_segment_without_a_speaker_is_not_a_cut(missing):
    segments = [seg(0, 0, 1, "É, tá", speaker_id=1), seg(1, 1.2, 2, "errado", speaker_id=2)]
    segments[missing]["speaker_id"] = None

    assert speaker_cuts(segments) == []
