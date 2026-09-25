"""Word error rate of several Transcriber outputs against one reference transcript.

The reference is a Gemini/Meet Markdown transcript (every "Name: text" line, bold
or not) or JSON as ``bench.wder`` reads it. Words are normalized as in
``bench.wder``: case, accents and punctuation do not count.
A Meet/Gemini reference is itself machine-made, so absolute WER overstates every
Engine's error; the comparison between hypotheses is what the number is for.

The first hypothesis is the baseline. For each other hypothesis the report lists
reference words that one of the two recognised and the other did not, which is
where proper nouns and technical terms show up. Usage:

    venv\\Scripts\\python.exe -m bench.asr_wer reference_gemini.md baseline.json candidate.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

from bench.wder import load_json_transcript, load_reference, tokenize

# "Name: text" or "**Name:** text". Unlike bench.wder, WER needs no speaker map, so
# any participant's line counts.
SPOKEN_LINE_PATTERN = re.compile(r"^(?:\*\*)?[^\W\d_][\w .'-]*?:(?:\*\*)?\s+(.+)$")


def reference_words(path: Path) -> list[str]:
    if path.suffix.lower() == ".json":
        return [word.text for word in load_reference(path)]
    words: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SPOKEN_LINE_PATTERN.match(line.strip())
        if match:
            words.extend(tokenize(match.group(1)))
    return words


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    """Levenshtein distance over words, one DP row at a time."""
    vocabulary = {word: index for index, word in enumerate(set(reference) | set(hypothesis))}
    ref = np.array([vocabulary[word] for word in reference])
    hyp = np.array([vocabulary[word] for word in hypothesis])
    columns = np.arange(len(hyp) + 1)
    row = columns.copy()
    for i, ref_word in enumerate(ref, 1):
        # Deletion and substitution first; insertions are a running minimum along the row.
        candidate = np.empty_like(row)
        candidate[0] = i
        candidate[1:] = np.minimum(row[1:] + 1, row[:-1] + (hyp != ref_word))
        row = np.minimum.accumulate(candidate - columns) + columns
    return int(row[-1])


def recognised_reference_indices(reference: list[str], hypothesis: list[str]) -> set[int]:
    matcher = SequenceMatcher(None, reference, hypothesis, autojunk=False)
    return {
        ref_start + offset
        for ref_start, _, size in matcher.get_matching_blocks()
        for offset in range(size)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", type=Path)
    parser.add_argument("hypotheses", type=Path, nargs="+", help="the first one is the baseline")
    parser.add_argument("--top", type=int, default=30, help="words listed per direction")
    parser.add_argument("--output", type=Path, help="optional JSON report")
    args = parser.parse_args()

    reference = reference_words(args.reference)
    hypotheses = {path: [word.text for word in load_json_transcript(path)] for path in args.hypotheses}

    report = {"reference": str(args.reference), "reference_words": len(reference), "hypotheses": []}
    print(f"reference: {len(reference)} words\n")
    print(f"{'hypothesis':<50} {'words':>6} {'WER':>7}")
    recognised = {}
    for path, words in hypotheses.items():
        errors = edit_distance(reference, words)
        recognised[path] = recognised_reference_indices(reference, words)
        wer = errors / len(reference)
        print(f"{path.name:<50} {len(words):>6} {wer:>7.2%}")
        report["hypotheses"].append({"path": str(path), "words": len(words), "errors": errors, "wer": round(wer, 4)})

    baseline = args.hypotheses[0]
    report["versus_baseline"] = []
    for candidate in args.hypotheses[1:]:
        gained = Counter(reference[i] for i in recognised[candidate] - recognised[baseline])
        lost = Counter(reference[i] for i in recognised[baseline] - recognised[candidate])
        print(f"\n{candidate.name} vs {baseline.name}: "
              f"+{sum(gained.values())} reference words recognised, -{sum(lost.values())}")
        print("  only candidate: " + ", ".join(f"{w}×{n}" for w, n in gained.most_common(args.top)))
        print("  only baseline:  " + ", ".join(f"{w}×{n}" for w, n in lost.most_common(args.top)))
        report["versus_baseline"].append(
            {"candidate": str(candidate), "gained": dict(gained.most_common()), "lost": dict(lost.most_common())}
        )

    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
