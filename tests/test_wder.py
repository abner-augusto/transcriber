from bench.wder import (
    LabeledWord,
    SHARED_ACCOUNT,
    evaluate,
    evaluate_with_review_queue,
    load_gemini_reference,
    mismatch_report,
    shared_account_review_queue,
)


def test_gemini_reference_normalizes_known_and_shared_speakers(tmp_path):
    path = tmp_path / "reference.md"
    path.write_text(
        "Chris Zamboni: Uma fala\nAbner Augusto Souza: Outra fala\n",
        encoding="utf-8",
    )

    words = load_gemini_reference(path)

    assert [(word.text, word.speaker) for word in words] == [
        ("uma", SHARED_ACCOUNT),
        ("fala", SHARED_ACCOUNT),
        ("outra", "ABNER"),
        ("fala", "ABNER"),
    ]


def test_wder_excludes_shared_account_and_finds_optimal_label_mapping():
    reference = [
        LabeledWord("um", "ABNER"),
        LabeledWord("dois", "ABNER"),
        LabeledWord("tres", SHARED_ACCOUNT),
        LabeledWord("quatro", SHARED_ACCOUNT),
        LabeledWord("cinco", "RICARDO"),
        LabeledWord("seis", "RICARDO"),
    ]
    hypothesis = [
        LabeledWord("um", "SPEAKER_01"),
        LabeledWord("dois", "SPEAKER_01"),
        LabeledWord("tres", "SPEAKER_02"),
        LabeledWord("quatro", "SPEAKER_02"),
        LabeledWord("cinco", "SPEAKER_03"),
        LabeledWord("seis", "SPEAKER_03"),
    ]

    result = evaluate(reference, hypothesis)

    assert result.shared_account_words == 2
    assert result.aligned_shared_account_words == 2
    assert result.aligned_evaluable_words == 4
    assert result.speaker_errors == 0
    assert result.wder == 0.0
    assert result.coverage == 1.0


def test_shared_account_review_queue_keeps_hypothesis_timestamps():
    reference = [LabeledWord("fala", SHARED_ACCOUNT, word_index=0)]
    hypothesis = [LabeledWord("fala", "GARRAH", 12.3, 13.4, source_index=7, word_index=0)]

    queue = shared_account_review_queue(reference, hypothesis)

    assert queue == [{
        "start": 12.3,
        "end": 13.4,
        "hypothesis_speaker": "GARRAH",
        "hypothesis_source_index": 7,
        "hypothesis_text": "fala",
        "reference_text": "fala",
        "hypothesis_word_indices": [0],
        "reference_word_indices": [0],
        "reference_speaker": SHARED_ACCOUNT,
        "resolved_speaker": None,
        "word_count": 1,
    }]


def test_review_queue_resolves_shared_account_for_full_wder():
    reference = [LabeledWord("fala", SHARED_ACCOUNT, word_index=0)]
    hypothesis = [LabeledWord("fala", "SPEAKER_01", word_index=0)]
    queue = {
        "items": [{
            "reference_word_indices": [0],
            "resolved_speaker": "chris",
        }]
    }

    result = evaluate_with_review_queue(reference, hypothesis, queue)

    assert result.shared_account_words == 0
    assert result.evaluable_reference_words == 1
    assert result.speaker_errors == 0
    assert result.wder == 0.0


def test_mismatch_report_includes_hypothesis_timestamps():
    reference = [
        LabeledWord("fala", "ABNER", word_index=0),
        LabeledWord("mais", "ABNER", word_index=1),
        LabeledWord("outra", "RICARDO", word_index=2),
        LabeledWord("final", "RICARDO", word_index=3),
    ]
    hypothesis = [
        LabeledWord("fala", "SPEAKER_01", 2.5, 3.5, word_index=0),
        LabeledWord("mais", "SPEAKER_01", 3.5, 4.5, word_index=1),
        LabeledWord("outra", "SPEAKER_01", 4.5, 5.5, word_index=2),
        LabeledWord("final", "SPEAKER_02", 5.5, 6.5, word_index=3),
    ]

    report = mismatch_report(reference, hypothesis)

    assert report["error_count"] == 1
    assert report["errors"] == [{
        "start": 4.5,
        "end": 5.5,
        "reference_word": "outra",
        "hypothesis_word": "outra",
        "reference_speaker": "RICARDO",
        "hypothesis_speaker": "SPEAKER_01",
        "mapped_hypothesis_speaker": "ABNER",
        "reference_word_index": 2,
        "hypothesis_word_index": 2,
    }]
