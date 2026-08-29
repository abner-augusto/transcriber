from bench.wder import LabeledWord, SHARED_ACCOUNT, evaluate, load_gemini_reference


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
