"""What a manual Segment edit teaches Vocabulary."""

import pytest

from transcript.vocabulary_correction import learned_from_edit


@pytest.mark.parametrize(
    "before, after, term",
    [
        ("o BWG, com", "o DWG, com", "DWG"),
        ("fui no pai ru ontem", "fui no Pacaembu ontem", "Pacaembu"),
        ("a outorga onerosa", "a Outorga Onerosa", "Outorga Onerosa"),
        ("no faixa 3 hoje", "no Faixa 3 hoje", "Faixa"),
        ("Fala outorga onerosa.", "Fala Outorga Onerosa.", "Outorga Onerosa"),
    ],
)
def test_an_edit_that_looks_like_a_term_teaches_it(before, after, term):
    terms, forms = learned_from_edit(before, after)

    assert terms == [term]
    assert [new for _, new in forms] in ([], [term])


@pytest.mark.parametrize(
    "before, after",
    [
        ("e tu falou com", "e o valor com"),
        ("com a mente", "com a medição"),
        ("Obrigada.", "Obrigado."),
        ("Ta ansioso", "Ta ansiosa"),
        ("foi 100", "foi 110"),
        ("[musica]", "[música]"),
        ("a prédio novo", "a prédios novo"),
    ],
)
def test_an_edit_of_common_words_teaches_nothing(before, after):
    assert learned_from_edit(before, after) == ([], [])


def test_a_sentence_initial_name_teaches_when_it_appears_capitalized_elsewhere():
    assert learned_from_edit("Galo disse", "Garrah disse") == ([], [])
    assert learned_from_edit("Galo disse", "Garrah disse", proper={"Garrah"}) == (
        ["Garrah"],
        [("Galo", "Garrah")],
    )
    assert learned_from_edit("Obrigada.", "Obrigado.", proper={"Garrah"}) == ([], [])


def test_a_known_term_is_learned_even_when_it_is_lowercase():
    assert learned_from_edit("sem habitese", "sem habite-se") == ([], [])
    assert learned_from_edit("sem habitese", "sem habite-se", known=("habite-se",)) == (
        ["habite-se"],
        [("habitese", "habite-se")],
    )


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
