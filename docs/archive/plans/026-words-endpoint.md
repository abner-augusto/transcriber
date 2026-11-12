# Plan 026: The API returns a Meeting's Words with their confidence

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c5cc40a..HEAD -- api/meetings.py transcript/words.py engines/ports.py`
> Any drift is a STOP condition until you have compared it against the
> excerpts below.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (one read-only route)
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `c5cc40a`, 2026-10-09
- **Source**: agent-friendliness audit, 2026-10-09

## Why this matters

An agent reviewing a transcript cannot hear the audio. Its best evidence is
which *Words* the Transcriber was unsure of. The app stores every Word with its
confidence (and optional CTC `alignment_score`) in `Meeting.raw_transcription`,
but no route returns them: a Segment carries only the mean confidence of its
Words. With this route, an agent (plan 030's `suspects` command) can point at
"`Galo` at 03:41, confidence 0.31" instead of "this paragraph looks off".

## Current state

- `models/meeting.py`: `raw_transcription: Mapped[dict] = mapped_column(JSON, nullable=True)`.
  `Meeting.to_dict` never includes it.
- `transcript/words.py` reads it back in whichever shape an older version wrote:

  ```python
  def words_from_stored(raw) -> list[Word]:
      """Words out of a Meeting's raw_transcription, whatever era wrote it.

      Meetings transcribed before the Transcriber port stored whisper's coarse segments
      as a bare list. Each is read back as one long Word ...
      """
  ```
- `engines/ports.py` `Word` fields: `start: float`, `end: float`, `text: str`
  (join-ready: it carries its own leading space), `confidence: float | None`,
  `alignment_score: float | None`. It has `to_dict()`.
- These are the Words **as heard**. Vocabulary Correction is applied later,
  when Segments are derived. A corrected Segment's text can differ from its
  Words, and the change is recorded in `Segment.corrections`
  (`{start, end, heard, term, rule}`).
- `api/meetings.py` ends with this route, the exemplar for a read route:

  ```python
  @router.get("/{meeting_id}/jobs")
  def list_jobs(meeting_id: str, db: Session = Depends(get_db)):
      jobs = db.query(Job).filter(Job.meeting_id == meeting_id).order_by(Job.created_at.desc()).all()
      return [j.to_dict() for j in jobs]
  ```
- Glossary: **Word** = "A single spoken word, with a start time, an end time,
  and a confidence ... what a Transcriber produces." Do not call them tokens.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| One file | `uv run pytest -q tests/test_meeting_api.py` | all pass |
| Backend gate | `uv run pytest -q tests` | 0 failures |

## Scope

**In scope**: `api/meetings.py`, `tests/test_meeting_api.py`.

**Out of scope**: `Meeting.to_dict` (keep `GET /meetings/{id}` unchanged;
Words for a 2-hour Meeting are large), `transcript/`, and the frontend.

## Git workflow

- Branch: `advisor/026-words-endpoint`; commit `feat(api): a Meeting's Words as heard, by time range`.
- Do not push.

## Steps

### Step 1: Route

Add to `api/meetings.py`:

```python
@router.get("/{meeting_id}/words")
def list_words(
    meeting_id: str,
    start: float | None = None,
    end: float | None = None,
    db: Session = Depends(get_db),
):
    """The Meeting's Words as the Transcriber heard them, before Vocabulary Correction.

    ``start``/``end`` (seconds) keep the Words that overlap that range.
    """
```

Behavior:
- 404 `"Meeting not found"`.
- 400 `"start must not exceed end"` when both are given and `start > end`.
- `words_from_stored(meeting.raw_transcription)`. An untranscribed Meeting
  returns `[]`.
- Keep a Word when `(end is None or w.start <= end) and (start is None or w.end >= start)`.
- Return `[w.to_dict() for w in kept]`, in stored order.

Import `words_from_stored` from `transcript.words` at module top.

**Verify**: the tests below pass.

## Test plan

In `tests/test_meeting_api.py`, model on `test_update_meeting_title_and_vocabulary`:

1. `test_words_returns_stored_words_with_confidence`: a Meeting with
   `raw_transcription={"words": [{"start":0,"end":0.4,"text":" Galo","confidence":0.31,"alignment_score":None}, {"start":0.5,"end":0.9,"text":" confirmou","confidence":0.92,"alignment_score":None}]}`
   returns both, with `confidence` 0.31 and 0.92.
2. `test_words_filters_by_time_range`: `?start=0.45&end=1` → only `" confirmou"`.
3. `test_words_of_an_untranscribed_meeting_is_empty` → `[]`.
4. `test_words_rejects_inverted_range` → 400.
5. `test_words_of_missing_meeting_is_404`.

Check the dict keys `Word.to_dict()` produces (`engines/ports.py`) before
writing the assertions.

## Done criteria

- [ ] `uv run pytest -q tests` exits 0 with the 5 new tests
- [ ] `GET /api/meetings/{id}` response is unchanged (no new keys) — the existing tests still pass
- [ ] `plans/README.md` row for 026 updated

## STOP conditions

- `Word.to_dict` does not exist or returns different keys than listed above.
- `raw_transcription` for a dict-shaped Meeting does not keep Words under `"words"`.

## Maintenance notes

- If Words ever move to their own table, this route keeps its shape and
  queries the table instead.
- A future Word-level UI (ticket 08, Correction suggestions) can reuse this route.
