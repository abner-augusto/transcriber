"""Pure Vocabulary Correction applied while deriving Segments."""

from dataclasses import dataclass, replace
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal

from engines import Word


# These conservative cutoffs are tuned by bench/vocabulary_correction.py.
SIMILAR_PHONETIC_RATIO = 0.85
SIMILAR_RATIO = 0.92
MAX_MERGE_GAP_SECONDS = 0.5


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

    @classmethod
    def for_meeting(
        cls, meeting_vocabulary: str | None, misheard: list[MisheardForm]
    ) -> "VocabularyCorrection":
        return cls(parse_vocabulary(meeting_vocabulary), misheard)

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
            [len(term.split()) + 1 for term in self.terms]
            + [len(form.heard.split()) + 1 for form in eligible]
            + [1]
        )
        matches: list[tuple[int, int, str, Literal["similar", "misheard"]]] = []
        for end in range(start + 1, min(len(words), start + max_words) + 1):
            if end > start + 1 and any(
                words[index].start - words[index - 1].end > MAX_MERGE_GAP_SECONDS
                for index in range(start + 1, end)
            ):
                break
            heard_norm = normalize_vocabulary_text("".join(word.text for word in words[start:end]))
            heard_spelling = "".join(word.text for word in words[start:end]).strip()
            if not heard_norm:
                continue
            for form in eligible:
                if heard_norm == normalize_vocabulary_text(form.heard):
                    matches.append((end, 2, form.term, "misheard"))
            for term in self.terms:
                term_norm = normalize_vocabulary_text(term)
                if len(_letters(term_norm)) < 4 or (
                    heard_norm == term_norm and heard_spelling == term
                ):
                    continue
                ratio = SequenceMatcher(None, heard_norm, term_norm).ratio()
                if (
                    ratio >= SIMILAR_PHONETIC_RATIO
                    and _phonetic_key("".join(word.text for word in words[start:end]))
                    == _phonetic_key(term)
                ) or ratio >= SIMILAR_RATIO:
                    matches.append((end, 1, term, "similar"))

        if not matches:
            return None
        # Misheard rules win; then prefer the longest word window. Stable input order
        # breaks ties between equally eligible Vocabulary terms.
        end, _, term, rule = max(matches, key=lambda item: (item[1], item[0]))
        return end, term, rule


def parse_vocabulary(text: str | None) -> list[str]:
    """Parse the Meeting format while accepting older free-form term lists."""
    if not text:
        return []
    terms: list[str] = []
    for line in text.splitlines() or [text]:
        if ":" in line:
            label, value = line.split(":", 1)
            normalized_label = normalize_vocabulary_text(label)
            if normalized_label in {"speaker", "speakers", "participante", "participantes"}:
                line = value
            elif normalized_label in {"vocabulary", "term", "terms", "termo", "termos", "vocabulario"}:
                line = value
        for item in re.split(r"[,;\n]", line):
            term = item.strip()
            if term and normalize_vocabulary_text(term) not in {
                normalize_vocabulary_text(existing) for existing in terms
            }:
                terms.append(term)
    return terms


def normalize_vocabulary_text(value: str) -> str:
    """Normalize terms and heard forms for accent/case/punctuation-insensitive comparison."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in plain if ch.isalnum())


def _letters(value: str) -> str:
    return "".join(ch for ch in value if ch.isalpha())


def _phonetic_key(value: str) -> str:
    """Small PT-BR key: folds common spelling variants, not a full phonetic model."""
    # Map cedilla before NFKD strips it and leaves a plain c behind.
    key = unicodedata.normalize("NFKD", value.casefold().replace("ç", "s"))
    key = "".join(
        char for char in key
        if not unicodedata.combining(char) and char.isalnum()
    )
    key = key.replace("ch", "\0")
    key = re.sub(r"(?<![cln])h", "", key)  # preserve ch, lh, and nh
    key = key.replace("ç", "s")
    key = re.sub(r"ss|sc(?=[ei])|c(?=[ei])", "s", key)
    key = re.sub(r"qu(?=[ei])|c", "k", key)
    key = re.sub(r"g(?=[ei])|j", "j", key)
    # ``ch`` was temporarily protected above, so restore its x sound here.
    key = key.replace("\0", "x")
    key = re.sub(r"(?<=[aeiou])z(?=[aeiou])", "s", key)
    key = key.replace("w", "v").replace("y", "i").replace("ph", "f")
    return re.sub(r"(.)\1+", r"\1", key)


def _replacement_word(words: list[Word], term: str) -> Word:
    first, last = words[0], words[-1]
    leading = re.match(r"\s*", first.text).group(0)
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
