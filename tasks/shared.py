import json
import logging

import redis

from config import settings
from engines import Turn, Word
from models import Job, Meeting

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


def build_segments(words: list[Word], turns: list[Turn]) -> list[dict]:
    """Derive the Segments a reader sees from a Transcriber's Words and a Diarizer's Turns.

    Every Word is attributed to the Speaker whose Turn it overlaps most. Segments then
    break wherever that Speaker changes — which is the whole point of working in Words:
    when someone cuts in mid-sentence, the interruption lands on its own line instead of
    being swallowed by whichever Speaker owned most of the sentence.

    Returns {start, end, text, speaker, confidence} dicts in time order.
    """
    attributed = [(word, _speaker_of(word, turns)) for word in words]

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


def _speaker_of(word: Word, turns: list[Turn]) -> str:
    """The Speaker who owns this Word: most overlap, else nearest, else nobody."""
    best_turn = None
    best_overlap = 0.0
    for turn in turns:
        overlap = min(word.end, turn.end) - max(word.start, turn.start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_turn = turn

    if best_turn is not None:
        return best_turn.speaker

    nearest = None
    nearest_gap = NEAREST_TURN_TOLERANCE_SECONDS
    for turn in turns:
        gap = max(turn.start - word.end, word.start - turn.end, 0.0)
        if gap <= nearest_gap:
            nearest_gap = gap
            nearest = turn

    return nearest.speaker if nearest else UNKNOWN_SPEAKER


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
