# 16 - The Vocabulary Bench Miscounts Two Kinds of Edit

**Source:** the user's review of the plan 014 bench, 2026-11-02.

**What happened:** of the 7 tokens `bench/vocabulary_correction.py` scored as
false changes, 3 were right corrections that the scoring could not match to
the user's edit:

1. **Case-only edits are invisible.** `_tokens` casefolds, so when the user
   changed `oferta terreno` to `Oferta Terreno` the manual diff records no
   change, and the correction that did the same thing counts as 2 false
   changes.
2. **A change next to an inserted word does not match.** The user turned
   `orçamentos RP.` into `orçamentos no ERP`. `SequenceMatcher` gives one
   `replace` opcode, `rp` → `noerp`, so the correction `RP.` → `ERP` matches
   nothing and counts as a false change.

The same gaps can also hide hits, so the reported hits are a floor.

**What to build:** score case-only edits (keep accents and case significant
when comparing a correction with the edit, or compare the correction's own
case change), and match a correction against the sub-span of a `replace`
opcode when the user's side only adds words around the corrected term.

**Acceptance:**
- Tests: a case-only edit plus the same correction scores a hit; `RP.` →
  `no ERP` with the correction `RP.` → `ERP` scores a hit, and the inserted
  `no` stays a miss.
- The bench re-run on the local database moves the two cases above to hits;
  record the new totals in `docs/archive/plans/014-vocabulary-correction.md`.
- The report stays metadata-only.

**Status:** done

The orchestrator will rerun the bench on the local database and record totals in plan 014.
