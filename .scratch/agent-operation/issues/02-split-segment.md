# 02 - Split a Segment the Diarizer joined

**Source:** first real operator session, 2026-10-09. The user said: "o
diarizador tende a separar a mesma pessoa e também juntar as falas em outros
trechos ... talvez valesse a feature de tentar quebrar mais as falas que foram
juntadas".

**Problem:** when one Segment holds two people, the only tools are `assign`,
which moves the whole Segment, and editing its text. Nothing cuts a Segment.

**Status:** needs-exploration. It comes after 01 (Review Notes), where a split
becomes one more kind of suggestion.

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
