"""Word-level diarization error evaluation for an annotated transcript sample.

The evaluator aligns normalized reference and hypothesis words by text, then scores
Speaker mismatches on aligned words. Reference words marked ``SHARED_ACCOUNT`` are
reported separately and excluded from the partial WDER denominator.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import permutations
from pathlib import Path


SHARED_ACCOUNT = "SHARED_ACCOUNT"

REFERENCE_SPEAKER_MAP = {
    "Abner Augusto Souza": "ABNER",
    "Camilla Lessa": "CAMILLA",
    "Chris Zamboni": SHARED_ACCOUNT,
    "Ricardo Albano": "RICARDO",
}

HYPOTHESIS_SPEAKER_MAP = {
    "Abner Augusto": "ABNER",
    "Camilla Lessa (OFC)": "CAMILLA",
    "Ricardo Albano (OFC)": "RICARDO",
    "Valdomiro Garrah": "GARRAH",
}

WORD_PATTERN = re.compile(r"[\w]+(?:['’][\w]+)*", re.UNICODE)
GEMINI_LINE_PATTERN = re.compile(
    r"^(Abner Augusto Souza|Camilla Lessa|Chris Zamboni|Ricardo Albano):\s*(.*)$"
)


@dataclass(frozen=True)
class LabeledWord:
    text: str
    speaker: str


@dataclass(frozen=True)
class Evaluation:
    reference_words: int
    hypothesis_words: int
    aligned_words: int
    evaluable_reference_words: int
    aligned_evaluable_words: int
    shared_account_words: int
    aligned_shared_account_words: int
    speaker_errors: int
    wder: float | None
    coverage: float
    speaker_mapping: dict[str, str | None]

    def to_dict(self) -> dict:
        return {
            "reference_words": self.reference_words,
            "hypothesis_words": self.hypothesis_words,
            "aligned_words": self.aligned_words,
            "evaluable_reference_words": self.evaluable_reference_words,
            "aligned_evaluable_words": self.aligned_evaluable_words,
            "shared_account_words": self.shared_account_words,
            "aligned_shared_account_words": self.aligned_shared_account_words,
            "speaker_errors": self.speaker_errors,
            "wder": self.wder,
            "coverage": self.coverage,
            "speaker_mapping": self.speaker_mapping,
        }


def normalize_word(text: str) -> str:
    """Normalize Portuguese text for ASR alignment without changing source text."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokenize(text: str) -> list[str]:
    return [normalize_word(match.group()) for match in WORD_PATTERN.finditer(text)]


def _labeled_tokens(text: str, speaker: str) -> list[LabeledWord]:
    return [LabeledWord(word, speaker) for word in tokenize(text)]


def _canonical_reference_speaker(speaker: str) -> str:
    return REFERENCE_SPEAKER_MAP.get(speaker, speaker)


def _canonical_hypothesis_speaker(speaker: str) -> str:
    return HYPOTHESIS_SPEAKER_MAP.get(speaker, speaker)


def load_gemini_reference(path: Path) -> list[LabeledWord]:
    words: list[LabeledWord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = GEMINI_LINE_PATTERN.match(line)
        if match:
            words.extend(_labeled_tokens(match.group(2), _canonical_reference_speaker(match.group(1))))
    return words


def load_json_transcript(path: Path, reference: bool = False) -> list[LabeledWord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("words") if isinstance(data, dict) and "words" in data else data.get("segments", [])
    words: list[LabeledWord] = []
    for entry in entries:
        speaker = entry.get("speaker", "UNKNOWN")
        if not reference:
            speaker = _canonical_hypothesis_speaker(speaker)
        elif isinstance(speaker, str):
            speaker = _canonical_reference_speaker(speaker)
        words.extend(_labeled_tokens(entry.get("text", ""), speaker))
    return words


def load_reference(path: Path) -> list[LabeledWord]:
    if path.suffix.lower() == ".json":
        return load_json_transcript(path, reference=True)
    return load_gemini_reference(path)


def _best_speaker_mapping(pairs: list[tuple[str, str]]) -> dict[str, str | None]:
    hypothesis_speakers = sorted({hypothesis for hypothesis, _ in pairs})
    reference_speakers = sorted({reference for _, reference in pairs})
    if not hypothesis_speakers:
        return {}

    targets = reference_speakers + [None] * max(0, len(hypothesis_speakers) - len(reference_speakers))
    best_score = -1
    best_mapping: dict[str, str | None] = {}
    for assignment in set(permutations(targets, len(hypothesis_speakers))):
        mapping = dict(zip(hypothesis_speakers, assignment))
        score = sum(mapping[hypothesis] == reference for hypothesis, reference in pairs)
        if score > best_score:
            best_score = score
            best_mapping = mapping
    return best_mapping


def evaluate(reference: list[LabeledWord], hypothesis: list[LabeledWord]) -> Evaluation:
    reference_text = [word.text for word in reference]
    hypothesis_text = [word.text for word in hypothesis]
    matcher = SequenceMatcher(None, reference_text, hypothesis_text, autojunk=False)
    aligned_pairs: list[tuple[LabeledWord, LabeledWord]] = []
    for ref_start, hyp_start, size in matcher.get_matching_blocks():
        aligned_pairs.extend(
            (reference[ref_index], hypothesis[hyp_index])
            for ref_index, hyp_index in zip(
                range(ref_start, ref_start + size), range(hyp_start, hyp_start + size)
            )
        )

    evaluable_pairs = [
        (ref_word, hyp_word)
        for ref_word, hyp_word in aligned_pairs
        if ref_word.speaker != SHARED_ACCOUNT
    ]
    mapping = _best_speaker_mapping(
        [(hyp_word.speaker, ref_word.speaker) for ref_word, hyp_word in evaluable_pairs]
    )
    errors = sum(
        mapping.get(hyp_word.speaker) != ref_word.speaker
        for ref_word, hyp_word in evaluable_pairs
    )
    evaluable_reference_words = sum(word.speaker != SHARED_ACCOUNT for word in reference)
    return Evaluation(
        reference_words=len(reference),
        hypothesis_words=len(hypothesis),
        aligned_words=len(aligned_pairs),
        evaluable_reference_words=evaluable_reference_words,
        aligned_evaluable_words=len(evaluable_pairs),
        shared_account_words=sum(word.speaker == SHARED_ACCOUNT for word in reference),
        aligned_shared_account_words=sum(
            ref_word.speaker == SHARED_ACCOUNT for ref_word, _ in aligned_pairs
        ),
        speaker_errors=errors,
        wder=errors / len(evaluable_pairs) if evaluable_pairs else None,
        coverage=(len(evaluable_pairs) / evaluable_reference_words) if evaluable_reference_words else 0.0,
        speaker_mapping=mapping,
    )


def evaluate_manifest(path: Path) -> Evaluation:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    reference = load_reference(Path(manifest["reference"]))
    hypothesis = load_json_transcript(Path(manifest["hypothesis"]))
    return evaluate(reference, hypothesis)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_manifest(args.manifest).to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
