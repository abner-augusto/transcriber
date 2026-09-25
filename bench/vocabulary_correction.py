"""Compare Vocabulary Correction with the user's edits in the local database.

Misheard Forms are learned again from the edits themselves, and each Meeting is
scored only with the forms learned from the other Meetings (leave-one-out), so a
Meeting never gets credit for a form it taught.

The report is deliberately metadata-only: Meeting IDs, Engine names, and token counts.
No transcript text, titles, Vocabulary, or correction forms are serialized or printed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import re

from database import SessionLocal
from models import Meeting, Segment
from transcript.diarization import MeetingDiarization
from transcript.segments import derive_segments
from transcript.vocabulary_correction import MisheardForm, VocabularyCorrection, learned_from_edit
from transcript.words import words_from_stored


DEFAULT_OUTPUT = Path("bench/out/vocabulary_correction.json")
EDIT_TIME_TOLERANCE_SECONDS = 1.5
TOKEN_PATTERN = re.compile(r"[\w]+(?:['’][\w]+)*", re.UNICODE)


@dataclass(frozen=True)
class MeetingCounts:
    meeting_id: str
    engine: str
    hits: int
    false_changes: int
    misses: int

    def to_dict(self) -> dict:
        # Explicit allowlist keeps private transcript content out of reports.
        return {
            "meeting_id": self.meeting_id,
            "engine": self.engine,
            "hits": self.hits,
            "false_changes": self.false_changes,
            "misses": self.misses,
        }


def _tokens(text: str) -> list[str]:
    # Keep accents significant here: an accent-only manual fix is still an edit
    # for the benchmark, even though correction matching ignores accents.
    return [match.group().casefold() for match in TOKEN_PATTERN.finditer(text)]


def _align_by_time(edited: Segment, derived: list[dict]) -> dict | None:
    candidates = []
    for segment in derived:
        start_delta = abs(segment["start"] - edited.start_time)
        end_delta = abs(segment["end"] - edited.end_time)
        if start_delta < EDIT_TIME_TOLERANCE_SECONDS and end_delta < EDIT_TIME_TOLERANCE_SECONDS:
            candidates.append((start_delta + end_delta, segment))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _manual_changes(before: str, after: str) -> list[tuple[str, str, int]]:
    """Return (heard phrase, user's phrase, changed-token count) from a word diff."""
    before_tokens = _tokens(before)
    after_tokens = _tokens(after)
    changes = []
    matcher = SequenceMatcher(None, before_tokens, after_tokens, autojunk=False)
    for operation, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        heard = "".join(before_tokens[a_start:a_end])
        wanted_tokens = after_tokens[b_start:b_end]
        wanted = "".join(wanted_tokens)
        count = len(wanted_tokens) or len(before_tokens[a_start:a_end])
        changes.append((heard, wanted, count))
    return changes


def _score_segment(edited: Segment, baseline: dict | None, corrected: dict | None):
    baseline_text = baseline["text"] if baseline else ""
    manual_changes = _manual_changes(baseline_text, edited.text)
    corrections = corrected.get("corrections", []) if corrected else []
    unmatched_manual = list(manual_changes)
    hits = false_changes = 0

    for correction in corrections:
        heard = "".join(_tokens(correction["heard"]))
        term = "".join(_tokens(correction["term"]))
        match_index = next((
            index for index, (manual_heard, wanted, _count) in enumerate(unmatched_manual)
            if manual_heard == heard and wanted == term
        ), None)
        if match_index is not None:
            _manual_heard, _wanted, count = unmatched_manual.pop(match_index)
            hits += count
        else:
            false_changes += len(_tokens(correction["term"]))

    misses = sum(count for _heard, _wanted, count in unmatched_manual)
    return hits, false_changes, misses


def _stored_words_and_diarization(meeting: Meeting):
    words = words_from_stored(meeting.raw_transcription)
    diarization = MeetingDiarization.from_stored(meeting.raw_diarization)
    if not words or diarization is None:
        raise ValueError(f"Meeting {meeting.id} is missing stored Words or diarization")
    return words, diarization


def learned_forms(meeting: Meeting, edited_segments: list[Segment]) -> Counter:
    """Count the (heard, term) Misheard Forms this Meeting's edits teach."""
    baseline = derive_segments(*_stored_words_and_diarization(meeting))
    forms: Counter = Counter()
    for edited in edited_segments:
        original = _align_by_time(edited, baseline)
        if original is not None:
            forms.update(learned_from_edit(original["text"], edited.text)[1])
    return forms


def held_out_forms(learned: dict[str, Counter], meeting_id: str) -> list[MisheardForm]:
    total: Counter = Counter()
    for other_id, forms in learned.items():
        if other_id != meeting_id:
            total.update(forms)
    return [MisheardForm(heard, term, count) for (heard, term), count in total.items()]


def score_meeting(meeting: Meeting, edited_segments: list[Segment], misheard_forms):
    words, diarization = _stored_words_and_diarization(meeting)
    baseline = derive_segments(words, diarization)
    correction = VocabularyCorrection.for_meeting(meeting.vocabulary, misheard_forms)
    corrected = derive_segments(words, diarization, correction=correction)

    totals = [0, 0, 0]
    for edited in edited_segments:
        original = _align_by_time(edited, baseline)
        updated = _align_by_time(edited, corrected)
        counts = _score_segment(edited, original, updated)
        totals = [total + count for total, count in zip(totals, counts)]

    raw = meeting.raw_transcription
    engine = raw.get("engine", "unknown") if isinstance(raw, dict) else "unknown"
    return MeetingCounts(meeting.id, str(engine or "unknown"), *totals)


def build_report(counts: list[MeetingCounts]) -> dict:
    return {
        "meetings": [item.to_dict() for item in counts],
        "totals": {
            "hits": sum(item.hits for item in counts),
            "false_changes": sum(item.false_changes for item in counts),
            "misses": sum(item.misses for item in counts),
        },
    }


def write_report(counts: list[MeetingCounts], output: Path = DEFAULT_OUTPUT) -> dict:
    report = build_report(counts)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def run(output: Path = DEFAULT_OUTPUT) -> dict:
    with SessionLocal() as db:
        edited_meetings = (
            db.query(Meeting)
            .join(Segment, Segment.meeting_id == Meeting.id)
            .filter(Segment.is_edited.is_(True))
            .distinct()
            .order_by(Meeting.id)
            .all()
        )
        edits = {
            meeting.id: (
                db.query(Segment)
                .filter(Segment.meeting_id == meeting.id, Segment.is_edited.is_(True))
                .order_by(Segment.order)
                .all()
            )
            for meeting in edited_meetings
        }
        learned = {meeting.id: learned_forms(meeting, edits[meeting.id]) for meeting in edited_meetings}
        counts = [
            score_meeting(meeting, edits[meeting.id], held_out_forms(learned, meeting.id))
            for meeting in edited_meetings
        ]

    report = write_report(counts, output)
    _print_report(counts, report["totals"])
    return report


def _print_report(counts: list[MeetingCounts], totals: dict) -> None:
    print(f"{'Meeting ID':36}  {'Engine':20}  {'Hits':>8}  {'False changes':>14}  {'Misses':>8}")
    for item in counts:
        print(
            f"{item.meeting_id:36}  {item.engine[:20]:20}  {item.hits:8}  "
            f"{item.false_changes:14}  {item.misses:8}"
        )
    print(
        f"{'TOTAL':36}  {'':20}  {totals['hits']:8}  "
        f"{totals['false_changes']:14}  {totals['misses']:8}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
