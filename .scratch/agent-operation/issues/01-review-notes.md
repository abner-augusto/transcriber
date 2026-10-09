# 01 - Review Notes: the agent asks, the user confirms, on the Meeting page

**Source:** first real operator session, 2026-10-09. The user said: "uma
feature de notas, ou indicações nas falas, para você deixar da mesma forma que
fez aqui, pedindo minha confirmação nos trechos que achou ambíguo".

**Problem:** the agent's questions and "re-listen" list live in the chat. To
answer, the user has to find each passage, play it, and type the answer back.
The Meeting page already has synced audio, live updates (plan 027) and a
sidebar with tabs (Speakers, Analytics), so the conversation fits there.

**Status:** ready-for-agent (plans 032, 033). Plan 032 (backend, CLI and
skill) is implemented; plan 033 (Meeting page) remains. The design was decided with the user on 2026-10-09. The full
list is in plan 032 "Decisions". Round 1 below was confirmed, with one change
to item 4: **the user creates descriptive comments only, never suggestions**,
because they edit text directly. Round 2 was settled as follows:

- resolved notes stay as history;
- accepting a name suggestion saves the Voice Profile by default;
- notes appear only in the JSON export;
- issue 08 will reuse this model later, as `author="system"`;
- the glossary name is "Review Note".

## Decisions, round 1 (confirmed)

1. **Anchor:** a time range (start/end seconds), not a Segment id. Segments
   are recreated on Reprocessing, so a note re-attaches to whichever Segment
   covers its range, by the same tolerance rule edits use (plan 028,
   `meeting_store._claim_nearest`). A range can also span several Segments.
2. **Kinds in v1:**
   - a free question ("who is this?");
   - a text suggestion ("Bineira" -> "Abner"), applied with one click;
   - a Speaker suggestion (name, move, merge).
   Split becomes a further kind once 02 lands.
3. **Accepting a text suggestion teaches Vocabulary by default**, because the
   click is the confirmation that `--learn` waits for today. A secondary
   "accept without teaching" stays available.
4. **Both the user and the agent create notes.** Each note records its
   author. A user note ("check this value") is read by the agent in the next
   session.

## Open for round 2

- Lifecycle: open -> accepted / dismissed / answered. Are resolved notes kept
  (history) or hidden?
- UI:
  - a marker on the Segment line;
  - a "Revisão" sidebar tab listing open notes;
  - a click seeks the audio;
  - Accept / Dismiss / Answer.
- CLI:
  - `note M #N "question"` and `suggest M #N "text"`;
  - `notes M [--open]` to read answers back;
  - JSON shape for agents.
- Export: do open notes appear in the export, e.g. as a "pendências de
  revisão" section for the minutes?
- Glossary name: "Review Note" / "Nota de revisão"?
- Issue 08 (show and accept or reject Vocabulary Corrections on the page): a
  Correction is "a suggestion awaiting the user's decision, anchored at a time
  range". Fold 08 into this model, with Corrections as system-authored notes,
  or keep it separate?
- ADR-0010 already allows this: notes are local Meeting data, and the agent
  writes them through the local API.

## Related

- 02-split-segment.md: a split is one more kind of suggestion.
- `.scratch/architecture-review/issues/08-correction-suggestions-ui.md`.
