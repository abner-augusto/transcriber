import json
import logging

import redis

from config import settings
from engines import DiarizationResult, Turn, Word
from models import Job, Meeting
from services.vad_service import mask_turns_to_vad

log = logging.getLogger(__name__)

# Module-level Redis connection pool (reused across all publish calls)
_redis_pool = redis.ConnectionPool.from_url(settings.redis_url)

# A Segment ends at a sentence, at a speaker change, at a long pause, or when it has
# simply run on too long to be a readable paragraph.
SENTENCE_ENDINGS = ".?!…"
MAX_PAUSE_SECONDS = 1.0
MAX_SEGMENT_SECONDS = 30.0

# A Word with no overlapping Turn is attributed to the nearest one within this gap —
# diarization leaves small holes, and a word in a hole still belongs to somebody.
NEAREST_TURN_TOLERANCE_SECONDS = 2.0

# Tunable penalty for switching speakers between adjacent words within the same turn
# (i.e. inter-word gap <= MAX_PAUSE_SECONDS). Prevents isolated single-word flaps while
# allowing sustained multi-word interruptions.
SPEAKER_SWITCH_PENALTY = 0.8

UNKNOWN_SPEAKER = "UNKNOWN"


def update_progress(db, job: Job, meeting: Meeting, progress: float, step: str):
    """Update job progress and broadcast via Redis pub/sub."""
    job.progress = progress
    job.current_step = step
    db.commit()

    publish_event(meeting.id, {
        "type": "progress",
        "progress": progress,
        "step": step,
        "status": meeting.status.value,
    })


def publish_event(meeting_id: str, data: dict):
    """Publish an event to Redis pub/sub for a meeting."""
    r = redis.Redis(connection_pool=_redis_pool)
    r.publish(f"meeting:{meeting_id}", json.dumps(data))


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

    candidate_set = {t.speaker for t in turns}
    candidates = sorted(candidate_set)
    candidates.append(UNKNOWN_SPEAKER)

    cand_order = {c: i for i, c in enumerate(candidates)}
    n_words = len(words)
    n_candidates = len(candidates)

    # Compute emission scores and tie-breaking keys for all (word, candidate)
    emissions: list[list[tuple[float, tuple[float, float, int]]]] = []
    for word in words:
        word_emissions = []
        for cand in candidates:
            score, tie_break = _candidate_emission(word, cand, turns, cand_order)
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
                    if c_prev == c_curr:
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
    turns: list[Turn],
    cand_order: dict[str, int],
) -> tuple[float, tuple[float, float, int]]:
    """Compute emission score and tie-breaking metadata for a candidate speaker on a word.

    Returns (score, (tie_break_start, tie_break_end, cand_index)).
    Higher score is better; for equal scores, smaller tie-breaking values are preferred.
    """
    cand_idx = cand_order.get(cand, 999999)

    if cand == UNKNOWN_SPEAKER:
        nearby_any = any(
            max(t.start - word.end, word.start - t.end, 0.0) <= NEAREST_TURN_TOLERANCE_SECONDS
            for t in turns
        )
        if not nearby_any:
            return (1.0, (0.0, 0.0, cand_idx))
        return (-1e6, (float("inf"), float("inf"), cand_idx))

    cand_turns = [t for t in turns if t.speaker == cand]
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
        score = 1.0 + overlap_ratio
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
        score = 1.0 - (best_gap / NEAREST_TURN_TOLERANCE_SECONDS)
        return (score, (best_turn.start, best_turn.end, cand_idx))

    return (-1e6, (float("inf"), float("inf"), cand_idx))


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


def words_from_stored(raw) -> list[Word]:
    """Words out of a Meeting's raw_transcription, whatever era wrote it.

    Meetings transcribed before the Transcriber port stored whisper's coarse segments
    as a bare list. Each is read back as one long Word — it has a start, an end and
    text, which is all a Word is — with the leading space the Word contract wants.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        return [Word.from_dict(w) for w in raw.get("words", [])]

    return [
        Word(
            start=float(item["start"]),
            end=float(item["end"]),
            text=" " + item["text"].strip(),
            confidence=item.get("confidence"),
        )
        for item in raw
        if item.get("text", "").strip()
    ]


def turns_from_stored(raw) -> list[Turn]:
    """Turns out of a Meeting's raw_diarization, whatever era wrote it."""
    if not raw:
        return []
    if isinstance(raw, dict):
        return [Turn.from_dict(t) for t in raw.get("turns", [])]
    return [Turn.from_dict(t) for t in raw]


def prepare_diarization(result, audio_path: str, vad_service) -> tuple[dict, list[Turn], list[Turn] | None]:
    """Normalize a diarizer result and retain both original and VAD-bounded Turns."""
    if isinstance(result, DiarizationResult):
        original_turns = result.turns
        original_exclusive = result.exclusive_turns
        supplied_overlaps = result.overlaps
    elif isinstance(result, dict):
        original_turns = [Turn.from_dict(t) for t in result.get("turns", [])]
        original_exclusive = (
            [Turn.from_dict(t) for t in result["exclusive_turns"]]
            if result.get("exclusive_turns") is not None
            else None
        )
        supplied_overlaps = result.get("overlaps")
    else:
        original_turns = list(result)
        original_exclusive = None
        supplied_overlaps = None

    vad_segments = vad_service.compute_vad_segments(audio_path)
    bounded_turns = vad_service.mask_turns_to_vad(original_turns, vad_segments)
    bounded_exclusive = (
        vad_service.mask_turns_to_vad(original_exclusive, vad_segments)
        if original_exclusive is not None
        else None
    )
    data = {
        "turns": [t.to_dict() for t in bounded_turns],
        "exclusive_turns": [t.to_dict() for t in bounded_exclusive] if bounded_exclusive is not None else None,
        "original_turns": [t.to_dict() for t in original_turns],
        "original_exclusive_turns": (
            [t.to_dict() for t in original_exclusive] if original_exclusive is not None else None
        ),
        "overlaps": supplied_overlaps if supplied_overlaps is not None else compute_overlaps(original_turns),
    }
    return data, bounded_turns, bounded_exclusive


def exclusive_turns_from_stored(raw) -> list[Turn] | None:
    """Exclusive turns out of a Meeting's raw_diarization if present."""
    if not raw or not isinstance(raw, dict):
        return None
    exclusive = raw.get("exclusive_turns")
    if exclusive is None:
        return None
    return [Turn.from_dict(t) for t in exclusive]


def attribution_turns_from_stored(raw) -> list[Turn]:
    """Turns used for Word/Segment attribution: exclusive turns if present, else original turns."""
    exclusive = exclusive_turns_from_stored(raw)
    if exclusive is not None and len(exclusive) > 0:
        return exclusive
    return turns_from_stored(raw)


def compute_overlaps(turns: list[Turn]) -> list[dict]:
    """Calculate time intervals where 2 or more distinct speakers overlap.

    Returns a list of {"start": float, "end": float, "speakers": list[str]} in time order.
    """
    if not turns or len(turns) < 2:
        return []

    boundaries = set()
    for t in turns:
        boundaries.add(round(t.start, 3))
        boundaries.add(round(t.end, 3))
    sorted_times = sorted(boundaries)

    raw_intervals: list[dict] = []
    for t0, t1 in zip(sorted_times, sorted_times[1:]):
        if t1 <= t0:
            continue
        active_speakers = {
            t.speaker for t in turns
            if round(t.start, 3) <= t0 and round(t.end, 3) >= t1
        }
        if len(active_speakers) >= 2:
            raw_intervals.append({
                "start": t0,
                "end": t1,
                "speakers": sorted(active_speakers),
            })

    if not raw_intervals:
        return []

    merged: list[dict] = []
    for interval in raw_intervals:
        if (
            merged
            and abs(merged[-1]["end"] - interval["start"]) < 1e-5
            and merged[-1]["speakers"] == interval["speakers"]
        ):
            merged[-1]["end"] = interval["end"]
        else:
            merged.append(dict(interval))

    return merged


def overlaps_from_stored(raw) -> list[dict]:
    """Overlap regions out of a Meeting's raw_diarization, computed if not explicitly stored."""
    if not raw:
        return []
    if isinstance(raw, dict) and "overlaps" in raw and raw["overlaps"] is not None:
        return raw["overlaps"]
    turns = turns_from_stored(raw)
    return compute_overlaps(turns)




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
