# 08 - Show Vocabulary Corrections on the Meeting Page

**Source:** design session on ticket 06, 2026-09-24 (user suggestion).

**What to build:** On the Meeting page, mark the Words that Vocabulary
Correction changed, the way low-confidence Segments are marked today (wavy
amber underline in `TranscriptView.tsx`), with the heard form on hover
("ouvido: Galo") and a way to accept or reject each Correction. A rejected
Correction could also teach an exception so the same Misheard Form stops
applying.

**Why:** Corrections happen silently after plan 014. Seeing them builds trust
and turns rejections into training data, which plan 014 deliberately left out
(decision 7).

**Blocked by:** plan 014 (needs `segments.corrections`).

**Status:** needs-exploration

**Open questions for the exploration session:**
- Word-level marks need Word positions inside Segment text; `corrections`
  stores times and strings. Match by string, or store character offsets?
- Does reject write an exception (new data) or delete the Misheard Form?
- Should low confidence also move from Segment level to Word level while
  this is being built?
