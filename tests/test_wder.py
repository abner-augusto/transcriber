from bench.wder import (
    LabeledWord,
    SHARED_ACCOUNT,
    evaluate,
    load_gemini_reference,
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
    reference = [LabeledWord("fala", SHARED_ACCOUNT)]
    hypothesis = [LabeledWord("fala", "GARRAH", 12.3, 13.4, source_index=7)]

    queue = shared_account_review_queue(reference, hypothesis)

    assert queue == [{
        "start": 12.3,
        "end": 13.4,
        "hypothesis_speaker": "GARRAH",
        "hypothesis_text": "fala",
        "reference_text": "fala",
        "reference_speaker": SHARED_ACCOUNT,
        "resolved_speaker": None,
        "word_count": 1,
    }]
