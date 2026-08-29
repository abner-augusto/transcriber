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
from dataclasses import dataclass, replace
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
    start: float | None = None
    end: float | None = None
    source_index: int | None = None
    word_index: int | None = None


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


def _labeled_tokens(
    text: str,
    speaker: str,
    start: float | None = None,
    end: float | None = None,
    source_index: int | None = None,
    word_offset: int = 0,
) -> list[LabeledWord]:
    return [
        LabeledWord(word, speaker, start, end, source_index, word_offset + index)
        for index, word in enumerate(tokenize(text))
    ]


def _canonical_reference_speaker(speaker: str) -> str:
    return REFERENCE_SPEAKER_MAP.get(speaker, speaker)


def _canonical_hypothesis_speaker(speaker: str) -> str:
    return HYPOTHESIS_SPEAKER_MAP.get(speaker, speaker)


def load_gemini_reference(path: Path) -> list[LabeledWord]:
    words: list[LabeledWord] = []
    for line_index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        match = GEMINI_LINE_PATTERN.match(line)
        if match:
            words.extend(
                _labeled_tokens(
                    match.group(2),
                    _canonical_reference_speaker(match.group(1)),
                    source_index=line_index,
                    word_offset=len(words),
                )
            )
    return words


def load_json_transcript(path: Path, reference: bool = False) -> list[LabeledWord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("words") if isinstance(data, dict) and "words" in data else data.get("segments", [])
    words: list[LabeledWord] = []
    for entry_index, entry in enumerate(entries):
        speaker = entry.get("speaker", "UNKNOWN")
        if not reference:
            speaker = _canonical_hypothesis_speaker(speaker)
        elif isinstance(speaker, str):
            speaker = _canonical_reference_speaker(speaker)
        words.extend(
            _labeled_tokens(
                entry.get("text", ""),
                speaker,
                float(entry["start"]) if entry.get("start") is not None else None,
                float(entry["end"]) if entry.get("end") is not None else None,
                source_index=entry_index,
                word_offset=len(words),
            )
        )
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
    aligned_pairs = _aligned_pairs(reference, hypothesis)

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


def _aligned_pairs(
    reference: list[LabeledWord], hypothesis: list[LabeledWord]
) -> list[tuple[LabeledWord, LabeledWord]]:
    matcher = SequenceMatcher(
        None,
        [word.text for word in reference],
        [word.text for word in hypothesis],
        autojunk=False,
    )
    pairs: list[tuple[LabeledWord, LabeledWord]] = []
    for ref_start, hyp_start, size in matcher.get_matching_blocks():
        pairs.extend(
            (reference[ref_index], hypothesis[hyp_index])
            for ref_index, hyp_index in zip(
                range(ref_start, ref_start + size), range(hyp_start, hyp_start + size)
            )
        )
    return pairs


def shared_account_review_queue(
    reference: list[LabeledWord], hypothesis: list[LabeledWord]
) -> list[dict]:
    """Group aligned shared-account words by timestamped hypothesis segment."""
    grouped: dict[int, dict] = {}
    fallback_index = 0
    for ref_word, hyp_word in _aligned_pairs(reference, hypothesis):
        if ref_word.speaker != SHARED_ACCOUNT:
            continue
        key = hyp_word.source_index if hyp_word.source_index is not None else fallback_index
        fallback_index += 1
        item = grouped.setdefault(
            key,
            {
                "start": hyp_word.start,
                "end": hyp_word.end,
                "hypothesis_speaker": hyp_word.speaker,
                "hypothesis_source_index": hyp_word.source_index,
                "hypothesis_text": [],
                "reference_text": [],
                "hypothesis_word_indices": [],
                "reference_word_indices": [],
                "reference_speaker": SHARED_ACCOUNT,
                "resolved_speaker": None,
            },
        )
        item["hypothesis_text"].append(hyp_word.text)
        item["reference_text"].append(ref_word.text)
        if hyp_word.word_index is not None:
            item["hypothesis_word_indices"].append(hyp_word.word_index)
        if ref_word.word_index is not None:
            item["reference_word_indices"].append(ref_word.word_index)

    queue = []
    for item in grouped.values():
        item["hypothesis_text"] = " ".join(item["hypothesis_text"])
        item["reference_text"] = " ".join(item["reference_text"])
        item["word_count"] = len(item["reference_text"].split())
        queue.append(item)
    return sorted(queue, key=lambda item: (item["start"] is None, item["start"] or 0.0))


def _resolve_reference_with_review_queue(
    reference: list[LabeledWord], queue: dict
) -> list[LabeledWord]:
    resolved_reference = list(reference)
    for item in queue.get("items", []):
        resolved_speaker = str(item.get("resolved_speaker") or "").strip().upper()
        if not resolved_speaker:
            continue
        if resolved_speaker not in {"CHRIS", "GARRAH"}:
            raise ValueError(
                f"Invalid resolved_speaker {resolved_speaker!r}; use CHRIS or GARRAH"
            )
        if "reference_word_indices" not in item:
            raise ValueError(
                "Review queue item has no reference_word_indices; regenerate the queue"
            )
        for word_index in item["reference_word_indices"]:
            if not isinstance(word_index, int) or not 0 <= word_index < len(resolved_reference):
                raise ValueError(f"Invalid reference_word_indices entry: {word_index!r}")
            if resolved_reference[word_index].speaker == SHARED_ACCOUNT:
                resolved_reference[word_index] = replace(
                    resolved_reference[word_index], speaker=resolved_speaker
                )
    return resolved_reference


def evaluate_with_review_queue(
    reference: list[LabeledWord], hypothesis: list[LabeledWord], queue: dict
) -> Evaluation:
    """Apply resolved shared-account labels to the reference before scoring."""
    return evaluate(_resolve_reference_with_review_queue(reference, queue), hypothesis)


def _apply_reference_speaker_overrides(
    reference: list[LabeledWord], overrides: dict[str, str]
) -> list[LabeledWord]:
    return [
        replace(word, speaker=overrides.get(word.speaker, word.speaker))
        for word in reference
    ]


def _load_manifest_transcripts(path: Path) -> tuple[dict, list[LabeledWord], list[LabeledWord]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    reference = load_reference(Path(manifest["reference"]))
    reference = _apply_reference_speaker_overrides(
        reference, manifest.get("reference_speaker_overrides", {})
    )
    hypothesis = load_json_transcript(Path(manifest["hypothesis"]))
    return manifest, reference, hypothesis


def mismatch_report(reference: list[LabeledWord], hypothesis: list[LabeledWord]) -> dict:
    """Return timestamped aligned words whose mapped speakers disagree."""
    evaluation = evaluate(reference, hypothesis)
    errors = []
    for ref_word, hyp_word in _aligned_pairs(reference, hypothesis):
        if ref_word.speaker == SHARED_ACCOUNT:
            continue
        mapped_speaker = evaluation.speaker_mapping.get(hyp_word.speaker)
        if mapped_speaker == ref_word.speaker:
            continue
        errors.append(
            {
                "start": hyp_word.start,
                "end": hyp_word.end,
                "reference_word": ref_word.text,
                "hypothesis_word": hyp_word.text,
                "reference_speaker": ref_word.speaker,
                "hypothesis_speaker": hyp_word.speaker,
                "mapped_hypothesis_speaker": mapped_speaker,
                "reference_word_index": ref_word.word_index,
                "hypothesis_word_index": hyp_word.word_index,
            }
        )
    return {
        "error_count": len(errors),
        "wder": evaluation.wder,
        "coverage": evaluation.coverage,
        "speaker_mapping": evaluation.speaker_mapping,
        "errors": errors,
    }


def error_report_manifest(path: Path, review_queue_path: Path | None = None) -> dict:
    manifest, reference, hypothesis = _load_manifest_transcripts(path)
    if review_queue_path:
        queue = json.loads(review_queue_path.read_text(encoding="utf-8"))
        reference = _resolve_reference_with_review_queue(reference, queue)
    report = mismatch_report(reference, hypothesis)
    report["sample_id"] = manifest["id"]
    return report


def evaluate_manifest(path: Path, review_queue_path: Path | None = None) -> Evaluation:
    _, reference, hypothesis = _load_manifest_transcripts(path)
    if review_queue_path:
        queue = json.loads(review_queue_path.read_text(encoding="utf-8"))
        return evaluate_with_review_queue(reference, hypothesis, queue)
    return evaluate(reference, hypothesis)


def review_queue_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    reference = load_reference(Path(manifest["reference"]))
    hypothesis = load_json_transcript(Path(manifest["hypothesis"]))
    items = shared_account_review_queue(reference, hypothesis)
    return {
        "sample_id": manifest["id"],
        "reference_speaker": SHARED_ACCOUNT,
        "items": items,
        "item_count": len(items),
        "word_count": sum(item["word_count"] for item in items),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--review-queue",
        type=Path,
        help="Write a timestamped queue for words labelled SHARED_ACCOUNT",
    )
    parser.add_argument(
        "--apply-review-queue",
        type=Path,
        help="Apply resolved_speaker values from a review queue before scoring",
    )
    parser.add_argument(
        "--error-report",
        type=Path,
        help="Write a timestamped JSON report of aligned speaker mismatches",
    )
    args = parser.parse_args()
    if args.review_queue and (args.apply_review_queue or args.error_report):
        parser.error("--review-queue cannot be combined with scoring options")
    if args.review_queue:
        queue = review_queue_manifest(args.manifest)
        args.review_queue.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({key: queue[key] for key in ("sample_id", "item_count", "word_count")}, indent=2))
        return
    if args.error_report:
        report = error_report_manifest(args.manifest, args.apply_review_queue)
        args.error_report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({key: report[key] for key in ("sample_id", "error_count", "wder", "coverage")}, indent=2))
        return
    print(
        json.dumps(
            evaluate_manifest(args.manifest, args.apply_review_queue).to_dict(),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
