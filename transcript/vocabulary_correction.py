"""Pure Vocabulary Correction applied while deriving Segments."""

from dataclasses import dataclass, replace
import re
import unicodedata
from difflib import SequenceMatcher
from collections.abc import Iterable
from typing import Literal

from engines import Word


# These conservative cutoffs are tuned by bench/vocabulary_correction.py.
SIMILAR_PHONETIC_RATIO = 0.85
SIMILAR_RATIO = 0.92
MAX_MERGE_GAP_SECONDS = 0.5
# A learned phrase this long is a rewrite, not a correction.
MAX_LEARNED_PHRASE_LENGTH = 100
# Words a multi-word name may contain without capitals ("Casa de Pedra").
_CONNECTORS = frozenset({"de", "da", "do", "das", "dos", "e"})
# Punctuation the transcript attaches to a word's edges; never part of a learned term or form.
EDGE_PUNCTUATION = ".,;:!?…\"'()[]"


@dataclass(frozen=True)
class MisheardForm:
    heard: str
    term: str
    count: int


@dataclass(frozen=True)
class Correction:
    start: float
    end: float
    heard: str
    term: str
    rule: Literal["similar", "misheard"]


@dataclass(frozen=True)
class VocabularyCorrection:
    """Everything needed to correct one Meeting's Words."""

    terms: list[str]
    misheard: list[MisheardForm]
    # Normalized (heard, term) pairs the user rejected: never corrected, by either rule.
    rejected: tuple[tuple[str, str], ...] = ()

    @classmethod
    def for_meeting(
        cls,
        meeting_vocabulary: str | None,
        misheard: list[MisheardForm],
        rejected: Iterable[tuple[str, str]] = (),
    ) -> "VocabularyCorrection":
        """``rejected`` holds (heard, term) pairs as written; they are normalized here."""
        return cls(
            parse_vocabulary(meeting_vocabulary),
            misheard,
            tuple(
                (normalize_vocabulary_text(heard), normalize_vocabulary_text(term))
                for heard, term in rejected
            ),
        )

    def apply(self, words: list[Word]) -> tuple[list[Word], list[Correction]]:
        if not words or (not self.terms and not self.misheard):
            return words, []

        output: list[Word] = []
        corrections: list[Correction] = []
        i = 0
        while i < len(words):
            match = self._match_at(words, i)
            if match is None:
                output.append(words[i])
                i += 1
                continue

            end_index, term, rule = match
            matched = words[i:end_index]
            heard = "".join(word.text for word in matched).strip()
            replacement = _replacement_word(matched, term)
            output.append(replacement)
            corrections.append(Correction(
                start=matched[0].start,
                end=matched[-1].end,
                heard=heard,
                term=term,
                rule=rule,
            ))
            i = end_index

        return (output, corrections) if corrections else (words, [])

    def _match_at(
        self, words: list[Word], start: int
    ) -> tuple[int, str, Literal["similar", "misheard"]] | None:
        eligible = [
            form for form in self.misheard
            if form.count >= 2 or normalize_vocabulary_text(form.term) in {
                normalize_vocabulary_text(term) for term in self.terms
            }
        ]
        max_words = max(
            [_window_limit(term) for term in self.terms]
            + [_window_limit(form.heard) for form in eligible]
            + [1]
        )
        matches: list[tuple[int, int, str, Literal["similar", "misheard"]]] = []
        for end in range(start + 1, min(len(words), start + max_words) + 1):
            window = end - start
            if end > start + 1 and any(
                words[index].start - words[index - 1].end > MAX_MERGE_GAP_SECONDS
                for index in range(start + 1, end)
            ):
                break
            if end > start + 1 and _ends_sentence(words[end - 2].text):
                break
            heard_norm = normalize_vocabulary_text("".join(word.text for word in words[start:end]))
            heard_spelling = without_edge_punctuation(
                "".join(word.text for word in words[start:end])
            )
            if not heard_norm:
                continue
            for form in eligible:
                if window > _window_limit(form.heard):
                    continue
                if heard_norm == normalize_vocabulary_text(form.heard) and (
                    heard_norm, normalize_vocabulary_text(form.term)
                ) not in self.rejected:
                    matches.append((end, 2, form.term, "misheard"))
            for term in self.terms:
                if window > _window_limit(term):
                    continue
                term_norm = normalize_vocabulary_text(term)
                if (heard_norm, term_norm) in self.rejected:
                    continue
                if len(_letters(term_norm)) < 4 or (
                    heard_norm == term_norm and heard_spelling == term
                ):
                    continue
                ratio = _similar_ratio("".join(word.text for word in words[start:end]), term)
                if ratio is None:
                    continue
                # A neighbouring Word that only dilutes the match is not part of the term.
                trimmed = [
                    _similar_ratio("".join(word.text for word in words[first:last]), term)
                    for first, last in ((start + 1, end), (start, end - 1))
                    if end - start > 1
                ]
                if any(other is not None and other >= ratio for other in trimmed):
                    continue
                matches.append((end, 1, term, "similar"))

        if not matches:
            return None
        # Misheard rules win; then prefer the longest word window. Stable input order
        # breaks ties between equally eligible Vocabulary terms.
        end, _, term, rule = max(matches, key=lambda item: (item[1], item[0]))
        return end, term, rule


def learned_from_edit(
    before: str,
    after: str,
    *,
    undone: set[tuple[str, str]] = frozenset(),
    known: Iterable[str] = (),
    proper: Iterable[str] = (),
) -> tuple[list[str], list[tuple[str, str]]]:
    """Return the terms and (heard, term) Misheard Forms a manual edit teaches.

    A replaced or inserted phrase becomes a term, and a replaced phrase is also a
    Misheard Form of it, only when it looks like a term (see ``_looks_like_term``).
    ``undone`` holds (term, heard) pairs of Corrections the edit may reverse:
    putting back what the Engine heard teaches nothing. ``known`` holds terms the
    Meeting already names (its Vocabulary, its participants): they always qualify.
    ``proper`` holds words the Meeting's text writes capitalized mid-sentence (see
    ``capitalized_mid_sentence``): their capital counts even at a sentence start.
    """
    if not before or not after or before.strip() == after.strip():
        return [], []
    reversed_pairs = {
        (normalize_vocabulary_text(term), normalize_vocabulary_text(heard))
        for term, heard in undone
    }
    known_terms = {normalize_vocabulary_text(term) for term in known}
    proper_words = frozenset(proper)
    old_words, new_words = before.split(), after.split()
    terms: list[str] = []
    forms: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, old_words, new_words).get_opcodes():
        new_phrase = " ".join(new_words[j1:j2]).strip(EDGE_PUNCTUATION)
        if not 2 <= len(new_phrase) < MAX_LEARNED_PHRASE_LENGTH:
            continue
        if normalize_vocabulary_text(new_phrase) not in known_terms and not _looks_like_term(
            new_words, j1, j2, proper_words
        ):
            continue
        if op == "insert":
            terms.append(new_phrase)
        elif op == "replace":
            old_phrase = " ".join(old_words[i1:i2]).strip(EDGE_PUNCTUATION)
            pair = (normalize_vocabulary_text(old_phrase), normalize_vocabulary_text(new_phrase))
            if pair in reversed_pairs:
                continue
            if abs(len(new_phrase) - len(old_phrase)) < len(old_phrase):
                terms.append(new_phrase)
                forms.append((old_phrase, new_phrase))
    return terms, forms


def capitalized_mid_sentence(texts: Iterable[str]) -> set[str]:
    """Words (edge punctuation stripped) the texts write capitalized away from a sentence start."""
    found: set[str] = set()
    for text in texts:
        words = text.split()
        for index in range(1, len(words)):
            if _ends_sentence(words[index - 1]):
                continue
            word = words[index].strip(EDGE_PUNCTUATION)
            letters = _letters(word)
            if letters and letters[0].isupper():
                found.add(word)
    return found


def _looks_like_term(
    words: list[str], start: int, end: int, proper: frozenset[str] = frozenset()
) -> bool:
    """Whether ``words[start:end]`` reads as a name or a technical term.

    Every word is capitalized, an acronym, a connector or a number, and at least
    one is capitalized or an acronym. A capital that only starts a sentence is no
    evidence, so "Obrigado." alone is not a term while "Pacaembu" mid-sentence is,
    unless the word is in ``proper``: the Meeting capitalizes it elsewhere too.
    """
    sentence_start = start == 0 or _ends_sentence(words[start - 1])
    evidence = False
    for index in range(start, end):
        word = words[index].strip(EDGE_PUNCTUATION)
        letters = _letters(word)
        if not letters or word.casefold() in _CONNECTORS:
            continue
        if word.isupper() and len(letters) >= 2:
            evidence = True
        elif letters[0].isupper():
            initial = index == start and sentence_start
            evidence = evidence or not initial or word in proper
        else:
            return False
    return evidence


def parse_vocabulary(text: str | None) -> list[str]:
    """Parse the Meeting format while accepting older free-form term lists."""
    if not text:
        return []
    terms: list[str] = []
    for line in text.splitlines() or [text]:
        if ":" in line:
            label, value = line.split(":", 1)
            if normalize_vocabulary_text(label) in _VOCABULARY_LABELS:
                line = value
        for item in re.split(r"[,;\n]", line):
            term = item.strip()
            if term and normalize_vocabulary_text(term) not in {
                normalize_vocabulary_text(existing) for existing in terms
            }:
                terms.append(term)
    return terms


_VOCABULARY_LABELS = {
    "speaker", "speakers", "participante", "participantes",
    "vocabulary", "term", "terms", "termo", "termos", "vocabulario",
}


def normalize_vocabulary_text(value: str) -> str:
    """Normalize terms and heard forms for accent/case/punctuation-insensitive comparison."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in plain if ch.isalnum())


def _letters(value: str) -> str:
    return "".join(ch for ch in value if ch.isalpha())


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _window_limit(phrase: str) -> int:
    """A phrase may be heard split into at most one more Word than it has."""
    return len(phrase.split()) + 1


def _similar_ratio(heard_text: str, term: str) -> float | None:
    """The match ratio when ``heard_text`` passes the ``similar`` test for ``term``, else None."""
    heard_norm, term_norm = normalize_vocabulary_text(heard_text), normalize_vocabulary_text(term)
    if _digits(heard_norm) != _digits(term_norm):
        return None
    ratio = SequenceMatcher(None, heard_norm, term_norm).ratio()
    if ratio >= SIMILAR_RATIO or (
        ratio >= SIMILAR_PHONETIC_RATIO and _phonetic_key(heard_text) == _phonetic_key(term)
    ):
        return ratio
    return None


def _ends_sentence(spelling: str) -> bool:
    return spelling.rstrip().rstrip("\"')]}»”’").endswith((".", "?", "!", "…"))


def without_edge_punctuation(spelling: str) -> str:
    return re.sub(r"^\W+|\W+$", "", spelling)


def _phonetic_key(value: str) -> str:
    """Small PT-BR key: folds common spelling variants, not a full phonetic model."""
    # Map cedilla before NFKD strips it and leaves a plain c behind.
    key = unicodedata.normalize("NFKD", value.casefold().replace("ç", "s"))
    key = "".join(
        char for char in key
        if not unicodedata.combining(char) and char.isalnum()
    )
    key = key.replace("ph", "f").replace("ch", "\0")
    key = re.sub(r"(?<![cln])h", "", key)  # preserve ch, lh, and nh
    key = re.sub(r"ss|sc(?=[ei])|c(?=[ei])", "s", key)
    key = re.sub(r"qu(?=[ei])|c", "k", key)
    key = re.sub(r"g(?=[ei])|j", "j", key)
    # ``ch`` was temporarily protected above, so restore its x sound here.
    key = key.replace("\0", "x")
    key = re.sub(r"(?<=[aeiou])z(?=[aeiou])", "s", key)
    key = key.replace("w", "v").replace("y", "i")
    return re.sub(r"(.)\1+", r"\1", key)


def _replacement_word(words: list[Word], term: str) -> Word:
    first, last = words[0], words[-1]
    leading = re.match(r"\W*", first.text).group(0)
    trailing_match = re.search(r"[^\w\s]+$", last.text)
    trailing = trailing_match.group(0) if trailing_match else ""
    confidences = [word.confidence for word in words if word.confidence is not None]
    alignments = [word.alignment_score for word in words if word.alignment_score is not None]
    return replace(
        first,
        end=last.end,
        text=f"{leading}{term}{trailing}",
        confidence=min(confidences) if confidences else None,
        alignment_score=min(alignments) if alignments else None,
    )
