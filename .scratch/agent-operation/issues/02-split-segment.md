# 02 - Split a Segment the Diarizer joined

**Source:** first real operator session, 2026-10-09. The user said: "o
diarizador tende a separar a mesma pessoa e também juntar as falas em outros
trechos ... talvez valesse a feature de tentar quebrar mais as falas que foram
juntadas".

**Problem:** when one Segment holds two people, the only tools are `assign`,
which moves the whole Segment, and editing its text. Nothing cuts a Segment.

**Status:** done for shape 1 (plans 035, 036 merged 2026-10-09). Shape 2
(Diarizer tuning) was benched on 2026-10-10; see "Bench, 2026-10-10" below. The design session ran on
2026-10-09. The user did not answer the questions, so the recommended options
were taken:
- shape 1, the manual split, now; shape 2 waits for a bench session;
- cut by Word (`--before "words"`) or by time (`--at`);
- the page gets the split only as a Review Note suggestion (036), not as
  a free-hand control.

A Split is stored as a time on the Meeting, so it survives every kind of
Reprocessing, Re-diarize included. A reassignment of the second half follows
plan 028's rules. Revisit the page control if the user asks for it.

## Two shapes to choose between, or do both in order

1. **A manual split.** A route plus a CLI command cut a Segment at a time or
   at a Word, using the stored Words (plan 026 `/words`), and assign each half
   to a Speaker.
   - It must survive Reprocessing the way reassignments do (plan 028), or be
     documented as dropped on Re-diarize.
   - It can be specified now.
2. **A Diarizer that switches more.** Tune `speaker_switch_penalty` and the
   Nemotron `clustering_threshold` in the RunConfig. This needs a bench run on
   the user's Meetings first (`bench/diarizer_wder.py`), since a lower penalty
   also splits single people more often, which is the opposite failure the
   user reported.

## Open questions

- What does the user cut by? A clock time, a Word, or the character position
  in the text?
- After Re-identify or Reapply Vocabulary, is a split re-applied (like a
  reassignment) or dropped?
- Does the UI get a split action too, or is it CLI and Review Note only?

## Bench, 2026-10-10

Before the bench, plan 037 fixed a bug: the saved `clustering_threshold` never
reached Nemotron, which ran with a literal `threshold=0.5`. Nemotron's knobs
are now Preferences (`speech_threshold`, `min_speaker_seconds`).

The setup: Sinop (`0d6197f6`, dual-track). Its reference is the current
Segments, and the 53 Words in hand-corrected Segments count as known. The
rest of the reference is the current output, so every disagreement there
was read by hand.

The control is `arquitetura-03`, single-track. It uses Meeting `096d74f9`
(the Parakeet copy, with stored Words and audio) and the hand-reviewed Gemini
reference, which now lives in
`D:\Nextcloud\_INTEGRARTE.ARQ\2-IAR_PROJETOS\1-ARQUITETURA\_2026\0-VIABILIDADES BRASIL URBANO\01 - SINOP - MT\5-BRIEFING_REUNIÕES`.
The paths in `bench/samples/2026-08-18-arquitetura-03/manifest*.json` are
stale. The control's WDER, with 4579 aligned Words and 79.6% coverage:
- the stored pyannote diarization: 1.57%;
- Nemotron at 0.5 and 0.8: 0.68%;
- penalty 0.6 to 0.8 is best (31 errors); 0.0 gives 38, 2.0 gives 41;
- `speech_threshold` 0.65 gives 26 errors against 31. In Sinop the same value
  is neutral to slightly worse: two new mid-sentence errors, two ambiguous
  changes, one known fix. That is too small a gain to act on;
- `min_speaker_seconds` 10: no change, because the smallest Speaker has 37 s.

Results:
- **`speaker_switch_penalty` from 0 to 2:** no value fixes a known Word below
  1.2. At 1.2 and above, the new mid-sentence errors outnumber the fixes. 0.8
  stays.
- **Raw Turns instead of exclusive Turns:** fixes 15 known Words, but adds 17
  new runs, mostly mid-sentence errors. Rejected.
- **Nemotron `speech_threshold` from 0.3 to 0.8:** a single forward pass
  extracted at each threshold. 0.5 reproduces the stored diarization exactly.
  At most 5 known Words get fixed (0.75), and new errors appear. 0.5 stays.
- **A constant Word/Turn time offset of ±0.1 to ±0.4 s:** always worse.
- **`min_speaker_seconds` 10 instead of 5:** the one clean win.
  - In Sinop it drops SPEAKER_03 (7.1 s), fixing 15 known Words (#124 to #127,
    Eduardo) with no new disagreement.
  - In `5068e1fa` it drops SPEAKER_01 (9.0 s). That Speaker's 9 Words go to
    SPEAKER_03, as the user's merge already did.
  - The other Nemotron Meetings do not change.

The remaining boundary errors are 1 to 3 Words at a handoff, in both
directions. Both channels are active there, and exclusive Turns leave the
Words to the nearest Turn. No global knob moves them without breaking other
handoffs. They stay an operator fix (`assign`).

The follow-ups landed on 2026-10-10:
- the user's Preference and the code default of `min_speaker_seconds` are now
  10 s (plan 038);
- `suspects` gained the section SENTENCE CUT BY A SPEAKER CHANGE (plan 039).
  On Sinop's uncorrected Segments it flags 29 pairs and finds 14 of the 17
  hand-fixed Segments.

Shape 2 is closed.
