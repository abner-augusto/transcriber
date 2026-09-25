from engines import Word
from transcript.vocabulary_correction import MisheardForm, VocabularyCorrection


def test_parses_formatted_and_legacy_vocabulary_deduplicating_case_insensitively():
    assert VocabularyCorrection.for_meeting(
        "Speakers: Ana, Bob\nVocabulary: Garrah, Docker; GARrah",
        [],
    ).terms == ["Ana", "Bob", "Garrah", "Docker"]
    assert VocabularyCorrection.for_meeting("São Paulo, C++; são paulo", []).terms == [
        "São Paulo", "C++"
    ]


def test_misheard_form_corrects_only_when_meeting_term_or_learned_twice():
    words = [Word(0, 0.4, " Galo")]
    eligible = VocabularyCorrection.for_meeting(
        "Vocabulary: Garrah", [MisheardForm("Galo", "Garrah", 1)]
    )
    ineligible = VocabularyCorrection.for_meeting(
        "", [MisheardForm("Galo", "Garrah", 1)]
    )
    learned = VocabularyCorrection.for_meeting(
        "", [MisheardForm("Galo", "Garrah", 2)]
    )
    assert eligible.apply(words)[0][0].text == " Garrah"
    assert ineligible.apply(words) == (words, [])
    assert learned.apply(words)[0][0].text == " Garrah"


def test_merges_adjacent_words_and_preserves_punctuation_and_word_metadata():
    words = [
        Word(0.1, 0.5, " Gar", 0.9, 0.8),
        Word(0.31, 0.4, " rah,", 0.7, 0.6),
    ]
    correction = VocabularyCorrection.for_meeting("Vocabulary: Garrah", [])
    result, changes = correction.apply(words)
    assert len(result) == 1
    assert result[0] == Word(0.1, 0.4, " Garrah,", 0.7, 0.6)
    assert changes[0].heard == "Gar rah,"
    assert (changes[0].start, changes[0].end, changes[0].rule) == (0.1, 0.4, "similar")


def test_cedilla_spelling_matches_its_pt_br_s_pronunciation():
    words = [Word(0, 0.5, " Asafrao")]
    correction = VocabularyCorrection.for_meeting("Açafrão", [])

    corrected, changes = correction.apply(words)

    assert corrected[0].text == " Açafrão"
    assert changes[0].term == "Açafrão"


def test_normalized_accent_and_case_variants_correct_but_three_letter_terms_do_not():
    words = [Word(0, 0.4, " Joao")]
    correction = VocabularyCorrection.for_meeting("João, Ana", [])
    assert correction.apply(words)[0][0].text == " João"
    assert VocabularyCorrection.for_meeting("Ana", []).apply(
        [Word(0, 0.4, " ana")]
    ) == ([Word(0, 0.4, " ana")], [])


def test_unrelated_common_word_is_unchanged_and_gap_blocks_merge():
    words = [Word(0, 0.2, " para"), Word(0.3, 0.5, "quedas")]
    correction = VocabularyCorrection.for_meeting("Parakeet", [])
    assert correction.apply(words) == (words, [])
    separated = [Word(0, 0.2, " Gar"), Word(0.71, 0.9, " rah")]
    assert VocabularyCorrection.for_meeting("Garrah", []).apply(separated) == (
        separated, []
    )


def test_no_correction_returns_the_original_word_list():
    words = [Word(0, 0.4, " falado")]
    corrected, changes = VocabularyCorrection.for_meeting(None, []).apply(words)
    assert corrected is words
    assert changes == []
