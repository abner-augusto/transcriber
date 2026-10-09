"""What a manual Segment edit teaches Vocabulary."""

from transcript.vocabulary_correction import learned_from_edit


def test_learned_phrases_lose_edge_punctuation():
    terms, forms = learned_from_edit("o BWG, com", "o DWG, com")

    assert terms == ["DWG"]
    assert forms == [("BWG", "DWG")]


def test_internal_punctuation_stays():
    terms, forms = learned_from_edit("sem o habitese, hoje", "sem o Habite-se, hoje")

    assert terms == ["Habite-se"]
    assert forms == [("habitese", "Habite-se")]


def test_a_phrase_that_is_only_punctuation_teaches_nothing():
    assert learned_from_edit("fim da fala", "fim da fala ...") == ([], [])
