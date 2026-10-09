---
name: transcriber-operator
description: Operate the local Transcriber app through its CLI. Use when transcribing a recording with this app, naming Speakers in a Meeting, or reviewing and correcting a Meeting's transcript. Also "transcrever", "revisar transcrição", "nomear falantes".
---

# Operating the Transcriber

You drive the running app with `uv run python -m transcriber_cli COMMAND`. Terms (Meeting, Speaker, Voice Profile, Vocabulary, Misheard Form) follow `GLOSSARY.md`; `docs/adr/0010-an-agent-may-operate-the-local-api.md` is why an agent may do this. `M` is a Meeting handle (id prefix or exact title), `#N` a Segment, `SPEAKER` a label or name. `--help` lists every flag.

Run each phase to its done-line, then move on. Every edit shows up on the open Meeting page without a reload, so tell the user they can watch it there.

## 1. Preflight

Run `health`. Exit 2 means the app is down: start it in the background (`./start.ps1` on Windows, `./start.sh` elsewhere) and repeat `health` until it exits 0.

**Done** when `health` exits 0.

Privacy: you read the transcript, and a hosted model carries that text off the machine. Say so once, unless the user already chose this. Audio paths and transcript text stay out of web tools.

## 2. Transcribe

Ask for the participants and the domain terms first; they are the best evidence for naming and correcting later. Then:

`upload FILE --title "..." --participants "A, B" --vocabulary "..." --process --wait`

**Done** when `wait` exits 0 (1 failed: show the error; 3 timed out). An existing Meeting skips this phase. Use `set M --participants ... --vocabulary ...` to add what you learn later.

## 3. Name Speakers

`speakers M --unnamed` lists the Speakers no Voice Profile matched and no person named, each with sample lines. It includes the dual-track HOST, which starts as "You".

**Shape first.** The Diarizer errs both ways, so read the Segments before and after each Speaker before naming it:

- A small Speaker (a handful of Segments, seconds of speech) is usually one person split in two. If it alternates with another Speaker within seconds, or its lines continue that Speaker's sentence, `merge M SOURCE TARGET` it and say so.
- One Speaker holding two people shows as lines that answer each other. Move their Segments with `add-speaker M NAME` (or `assign M #N new:NAME`) and `assign M #N SPEAKER`, and tell the user which Segments moved.
- A loudspeaker, TV or other room the mic picked up gets its own Speaker: `assign M #N new:"Alto-falante"`. Its text stays as heard, and no participant gets it.

**Then name**, on evidence, strongest first:

1. a self-introduction;
2. being addressed by name, then that Speaker answering;
3. the participants list combined with role and topic.

A name heard once may itself be misheard. Compare it with the regulars before applying it: Voice Profile names, the Speakers of the user's other Meetings with the same title pattern (`list`, then `speakers`), and the participants list. A regular who sounds close ("Luiz" for "Lourdes") wins over a new name. In a recurring meeting, ask the user before naming someone new.

The dual-track HOST is the user (the mic owner): `rename` "You" to their name.

Quote the evidence with its Segment handles when you propose a name. Without evidence, ask the user, showing the samples and timestamps.

`rename M SPEAKER NAME` applies a name. Add `--save-profile` after the user confirms the name: it makes future Meetings name that voice automatically.

**Done** when `speakers M --unnamed` is empty, or each remaining Speaker has a question put to the user.

## 4. Review

`suspects M` prints up to three sections. For each hit, `show M --from T --to T` reads the passage in context (a filtered `show` prints Segments only), and `words M --from T --to T --below 0.6` shows the Words as heard. To find a name, number or term, `show M --grep PATTERN` (case-insensitive regex; combines with `--speaker`, `--from`, `--to`).

| Section | Reading |
|---|---|
| REPEATED | The same sentence back to back is a Transcriber filling silence. Report the time range; the text is not yours to fix. |
| LOW-CONFIDENCE PASSAGES (worst first) | Segments holding Words under 0.4, each line ending `weak: word 0.14, ...`. Start at the top; a very low Word inside a name or term is the likeliest error. |
| CORRECTED BY VOCABULARY | Check each `heard->term` fix against the context. |

Read the transcript yourself for two failures no command finds: a side conversation an open mic captured (a long off-topic block from someone who barely speaks otherwise) and plausible-sounding numbers. Report an implausible number to the user with its handle; the number stays as transcribed.

Fix a passage with `edit M #N "text"` only when the transcript supports the fix: a term in the vocabulary or participants, the same word spelled right elsewhere, or an obvious grammar mishearing in context. Everything else goes to the user as `#N clock "heard" -> "maybe"`, for them to re-listen.

**Done** when every `suspects` entry is fixed, reported as a time range, or listed for the user.

## 5. Hand off

Report what you named, what you edited (Segment handles), and the re-listen list. For a meeting record, `export M --format json --out FILE` feeds the user's minutes workflow, if they have one; this skill ends at a reviewed transcript.

## Learning and undo

- `edit` teaches Vocabulary only with `--learn`, and a learned Misheard Form applies to every future Meeting. Pass `--learn` only for corrections the user confirmed.
- To teach a new term, first `edit --learn` changing only the misheard words, then fix the rest of the sentence in a second `edit` without `--learn`. Only short replaced phrases are learned, so a whole-sentence rewrite teaches nothing.
- `revert M #N` undoes a text edit.
- Names and reassignments survive `reprocess reidentify` and `reprocess reapply-vocabulary`. `reprocess rediarize` carries names by Turn overlap and drops reassignments, so warn the user before suggesting it.

## Line markers

`[edited]` text changed by hand, `[moved]` Speaker changed by hand, `[conf 0.41]` Segment confidence under 0.6, `[fixed: heard->term]` a Vocabulary Correction.

## Commands

`health` · `list` · `upload` · `process` · `reprocess KIND` · `wait` · `show` · `speakers` · `words` · `suspects` · `rename` · `add-speaker` · `merge` · `edit` · `revert` · `assign` · `set` · `export`. Add `--json` before the command for the API's raw JSON.
