"""Segments: the lines a reader sees, derived from Words and a Meeting's Turns.

Every Word is attributed to a Speaker by sequence-level smoothing over Turn evidence,
then Segments break at speaker changes, sentence ends, long pauses, and length limits.
Pure: no database, no Redis, no Engine.
"""

from bisect import bisect_right
from dataclasses import dataclass
import math

from engines import Turn, Word
from .diarization import MeetingDiarization
from .vocabulary_correction import Correction, VocabularyCorrection


# A Segment ends at a sentence, at a speaker change, at a long pause, or when it has
# simply run on too long to be a readable paragraph.
SENTENCE_ENDINGS = ".?!…"
MAX_PAUSE_SECONDS = 1.0
MAX_SEGMENT_SECONDS = 30.0

# A Word with no overlapping Turn is attributed to the nearest one within this gap —
# diarization leaves small holes, and a word in a hole still belongs to somebody.
NEAREST_TURN_TOLERANCE_SECONDS = 2.0

# Emissions range from 0 to 2. Entering and leaving a one-Word interruption costs
# twice this value, so the 0.8 default requires more evidence than one Word can supply.
SPEAKER_SWITCH_PENALTY = 0.8

UNKNOWN_SPEAKER = "UNKNOWN"


@dataclass(frozen=True)
class _TurnIndex:
    turns: list[Turn]
    starts: list[float]
    tree_size: int
    max_ends: list[float]

    @classmethod
    def build(cls, turns: list[Turn]) -> "_TurnIndex":
        ordered = sorted(turns, key=lambda turn: (turn.start, turn.end, turn.speaker))
        starts = [turn.start for turn in ordered]
        tree_size = 1
        while tree_size < len(ordered):
            tree_size *= 2
        max_ends = [-float("inf")] * (2 * tree_size)
        for index, turn in enumerate(ordered):
            max_ends[tree_size + index] = turn.end
        for index in range(tree_size - 1, 0, -1):
            max_ends[index] = max(max_ends[index * 2], max_ends[index * 2 + 1])
        return cls(ordered, starts, tree_size, max_ends)

    def near(self, word: Word) -> list[Turn]:
        """Turns that overlap the Word or lie within attribution tolerance."""
        low = word.start - NEAREST_TURN_TOLERANCE_SECONDS
        high = word.end + NEAREST_TURN_TOLERANCE_SECONDS
        stop = bisect_right(self.starts, high)
        matches: list[Turn] = []
        stack = [(1, 0, self.tree_size)]
        while stack:
            node, start, end = stack.pop()
            if start >= stop or self.max_ends[node] < low:
                continue
            if end - start == 1:
                if start < len(self.turns):
                    matches.append(self.turns[start])
                continue
            middle = (start + end) // 2
            stack.append((node * 2 + 1, middle, end))
            stack.append((node * 2, start, middle))
        return matches


def smooth_word_speakers(
    words: list[Word],
    turns: list[Turn],
    switch_penalty: float = SPEAKER_SWITCH_PENALTY,
) -> list[str]:
    """Assign speakers to a sequence of words using Viterbi DP smoothing.

    Emission score is based on turn overlap (or nearest turn gap within tolerance).
    Switching speaker between adjacent words incurs `switch_penalty`, waived when
    the inter-word gap exceeds MAX_PAUSE_SECONDS.
    """
    if not words:
        return []
    if not turns:
        return [UNKNOWN_SPEAKER] * len(words)

    turns_by_speaker: dict[str, list[Turn]] = {}
    for turn in turns:
        turns_by_speaker.setdefault(turn.speaker, []).append(turn)
    candidates = sorted(turns_by_speaker)
    candidates.append(UNKNOWN_SPEAKER)

    indexes = {
        speaker: _TurnIndex.build(speaker_turns)
        for speaker, speaker_turns in turns_by_speaker.items()
    }
    cand_order = {c: i for i, c in enumerate(candidates)}
    n_words = len(words)
    n_candidates = len(candidates)

    # Compute emission scores and tie-breaking keys for all (word, candidate)
    emissions: list[list[tuple[float, tuple[float, float, int]]]] = []
    for word in words:
        word_emissions = []
        nearby_any = False
        for cand in candidates:
            candidate_turns = indexes[cand].near(word) if cand in indexes else []
            nearby_any = nearby_any or bool(candidate_turns)
            score, tie_break = _candidate_emission(
                word,
                cand,
                candidate_turns,
                cand_order,
                nearby_any,
            )
            word_emissions.append((score, tie_break))
        emissions.append(word_emissions)

    # dp[i][c]: best cumulative score ending at word i with candidate c
    # backpointer[i][c]: candidate index at word i-1
    dp: list[list[float]] = [[0.0] * n_candidates for _ in range(n_words)]
    backpointer: list[list[int]] = [[0] * n_candidates for _ in range(n_words)]

    for c in range(n_candidates):
        dp[0][c] = emissions[0][c][0]

    for i in range(1, n_words):
        prev_word = words[i - 1]
        curr_word = words[i]
        pause_exceeded = (curr_word.start - prev_word.end) > MAX_PAUSE_SECONDS

        for c_curr in range(n_candidates):
            best_prev_score = -float("inf")
            best_prev_c = 0

            for c_prev in range(n_candidates):
                penalty = 0.0 if (c_prev == c_curr or pause_exceeded) else switch_penalty
                score = dp[i - 1][c_prev] - penalty

                if score > best_prev_score:
                    best_prev_score = score
                    best_prev_c = c_prev
                elif abs(score - best_prev_score) < 1e-9:
                    current_stays = c_prev == c_curr
                    best_stays = best_prev_c == c_curr
                    if current_stays and not best_stays:
                        best_prev_score = score
                        best_prev_c = c_prev
                    elif current_stays == best_stays and (
                        emissions[i - 1][c_prev][1] < emissions[i - 1][best_prev_c][1]
                    ):
                        best_prev_score = score
                        best_prev_c = c_prev

            dp[i][c_curr] = best_prev_score + emissions[i][c_curr][0]
            backpointer[i][c_curr] = best_prev_c

    # Find best final candidate
    best_final_c = 0
    best_final_key = None
    for c in range(n_candidates):
        score = dp[n_words - 1][c]
        tie_break = emissions[n_words - 1][c][1]
        cand_key = (score, -tie_break[0], -tie_break[1], -tie_break[2])
        if best_final_key is None or cand_key > best_final_key:
            best_final_key = cand_key
            best_final_c = c

    # Backtrack
    result_indices = [0] * n_words
    curr_c = best_final_c
    for i in range(n_words - 1, -1, -1):
        result_indices[i] = curr_c
        curr_c = backpointer[i][curr_c]

    return [candidates[idx] for idx in result_indices]


def _candidate_emission(
    word: Word,
    cand: str,
    cand_turns: list[Turn],
    cand_order: dict[str, int],
    nearby_any: bool,
) -> tuple[float, tuple[float, float, int]]:
    """Compute emission score and tie-breaking metadata for a candidate speaker on a word.

    Returns (score, (tie_break_start, tie_break_end, cand_index)).
    Higher score is better; for equal scores, smaller tie-breaking values are preferred.
    """
    cand_idx = cand_order.get(cand, 999999)

    if cand == UNKNOWN_SPEAKER:
        if not nearby_any:
            return (1.0, (0.0, 0.0, cand_idx))
        return (-1e6, (float("inf"), float("inf"), cand_idx))

    if not cand_turns:
        return (-1e6, (float("inf"), float("inf"), cand_idx))

    overlapping = []
    for t in cand_turns:
        overlap = min(word.end, t.end) - max(word.start, t.start)
        if overlap > 0:
            overlapping.append((round(overlap, 6), t))

    if overlapping:
        best_overlap, best_turn = min(
            overlapping,
            key=lambda item: (-item[0], item[1].start, item[1].end, item[1].speaker),
        )
        total_overlap = sum(item[0] for item in overlapping)
        word_dur = max(word.end - word.start, 1e-6)
        overlap_ratio = min(total_overlap / word_dur, 1.0)
        score = (1.0 + overlap_ratio) * _alignment_weight(word)
        return (score, (best_turn.start, best_turn.end, cand_idx))

    nearby = []
    for t in cand_turns:
        gap = max(t.start - word.end, word.start - t.end, 0.0)
        if gap <= NEAREST_TURN_TOLERANCE_SECONDS:
            nearby.append((round(gap, 6), t))

    if nearby:
        best_gap, best_turn = min(
            nearby,
            key=lambda item: (item[0], item[1].start, item[1].end, item[1].speaker),
        )
        score = (1.0 - (best_gap / NEAREST_TURN_TOLERANCE_SECONDS)) * _alignment_weight(word)
        return (score, (best_turn.start, best_turn.end, cand_idx))

    return (-1e6, (float("inf"), float("inf"), cand_idx))


def _alignment_weight(word: Word) -> float:
    if word.alignment_score is None or not math.isfinite(word.alignment_score):
        return 1.0
    return max(min(max(word.alignment_score, 0.0), 1.0), 0.2)


def build_segments(
    words: list[Word],
    turns: list[Turn],
    switch_penalty: float = SPEAKER_SWITCH_PENALTY,
) -> list[dict]:
    """Derive the Segments a reader sees from a Transcriber's Words and a Diarizer's Turns.

    Every Word is attributed to a Speaker using sequence-level smoothing based on
    Turn overlap and proximity evidence. Segments then break wherever that Speaker
    changes — which is the whole point of working in Words: when someone cuts in
    mid-sentence, a sustained interruption lands on its own line instead of being
    swallowed by whichever Speaker owned most of the sentence, while isolated single-word
    flaps are smoothed away.

    Returns {start, end, text, speaker, confidence} dicts in time order.
    """
    if not words:
        return []

    speakers = smooth_word_speakers(words, turns, switch_penalty=switch_penalty)
    attributed = list(zip(words, speakers))

    segments: list[dict] = []
    current: list[tuple[Word, str]] = []

    for word, speaker in attributed:
        if current and _breaks_before(current, word, speaker):
            segments.append(_close(current))
            current = []
        current.append((word, speaker))

    if current:
        segments.append(_close(current))

    return segments


def derive_segments(
    words: list[Word],
    diarization: MeetingDiarization | None,
    switch_penalty: float = SPEAKER_SWITCH_PENALTY,
    correction: VocabularyCorrection | None = None,
) -> list[dict]:
    """The Segments a reader sees for a Meeting's Words and its diarization.

    Words are attributed against the diarization's exclusive Turns when it has any,
    else its Turns. With no diarization every Word is UNKNOWN.
    """
    turns = diarization.attribution_turns if diarization is not None else []
    corrected_words, corrections = correction.apply(words) if correction else (words, [])
    segments = build_segments(corrected_words, turns, switch_penalty=switch_penalty)
    for segment in segments:
        segment_corrections = [
            item for item in corrections
            if item.start >= segment["start"] and item.end <= segment["end"]
        ]
        segment["corrections"] = [
            {
                "start": item.start,
                "end": item.end,
                "heard": item.heard,
                "term": item.term,
                "rule": item.rule,
            }
            for item in segment_corrections
        ]
    return segments


def _breaks_before(current: list[tuple[Word, str]], word: Word, speaker: str) -> bool:
    last_word, last_speaker = current[-1]

    if speaker != last_speaker:
        return True
    if last_word.text.rstrip().endswith(tuple(SENTENCE_ENDINGS)):
        return True
    if word.start - last_word.end > MAX_PAUSE_SECONDS:
        return True
    if word.end - current[0][0].start > MAX_SEGMENT_SECONDS:
        return True
    return False


def _close(current: list[tuple[Word, str]]) -> dict:
    words = [word for word, _ in current]
    confidences = [w.confidence for w in words if w.confidence is not None]

    return {
        "start": words[0].start,
        "end": max(w.end for w in words),
        "text": "".join(w.text for w in words).strip(),
        "speaker": current[0][1],
        "confidence": sum(confidences) / len(confidences) if confidences else None,
    }
