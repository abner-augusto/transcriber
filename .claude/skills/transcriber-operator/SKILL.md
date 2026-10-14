---
name: transcriber-operator
description: Operate the local Transcriber app through its CLI. Use when transcribing a recording with this app, naming Speakers in a Meeting, or reviewing and correcting a Meeting's transcript. Also "transcrever", "revisar transcrição", "nomear falantes".
---

# Operating the Transcriber

You drive the running app with `uv run python -m transcriber_cli COMMAND`. Terms (Meeting, Speaker, Voice Profile, Vocabulary, Misheard Form) follow `GLOSSARY.md`; `docs/adr/0010-an-agent-may-operate-the-local-api.md` is why an agent may do this. `M` is a Meeting handle (id prefix or exact title), `#N` a Segment, `SPEAKER` a label or name. `--help` lists every flag.

Run each phase to its done-line, then move on. Every edit shows up on the open Meeting page without a reload, so tell the user they can watch it there.

A **Review Note** is how you ask the user something about a passage: it sits at a time range of the Meeting, and the user answers or accepts it on the Meeting page. When the evidence is not enough to act, leave a note; a chat question sends the user hunting for the passage. Direct `edit`, `rename`, `merge` and `assign` stay for what the transcript proves.

Each note carries one proposal. Accept applies it, and Dismiss means the passage stays as it is. A dismissed note is therefore settled, often because the user heard a real interruption. When you see two possible fixes, leave one note per fix.

## 1. Preflight

Run `health`. Exit 2 means the app is down: start it in the background (`./start.ps1` on Windows, `./start.sh` elsewhere) and repeat `health` until it exits 0.

For an existing Meeting, the user's replies come next. `notes M --status answered` lists the answers to your questions, and `notes M --status open` lists open notes, where author `user` marks the user's own comments. Act on each reply, then `close M NOTE --reply "..."` with a short account of what you did.

**Done** when `health` exits 0 and every reply is acted on and closed.

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
- One Segment holding two people (a question and its answer on one line): `split M #N --before "first words of the second half" --speaker SPEAKER`. Split only when the text shows the change of speaker: a question then its answer, a name addressed then answering. `show` again afterwards, because later handles shift; `unsplit M #N` takes a Split back. When the text does not show where the second person starts, `suggest-split M #N (--before "words" | --at T) [--speaker SPEAKER|new:NAME] --why "..."` leaves the cut as a note for the user to accept.
- A loudspeaker, TV or other room the mic picked up gets its own Speaker: `assign M #N new:"Alto-falante"`. Its text stays as heard, and no participant gets it.

**Then name**, on evidence, strongest first:

1. a self-introduction;
2. being addressed by name, then that Speaker answering;
3. the participants list combined with role and topic.

A name heard once may itself be misheard. Compare it with the regulars before applying it: Voice Profile names, the Speakers of the user's other Meetings with the same title pattern (`list`, then `speakers`), and the participants list. A regular who sounds close ("Luiz" for "Lourdes") wins over a new name. In a recurring meeting, propose a new name as a note instead of applying it.

The dual-track HOST is the user (the mic owner): `rename` "You" to their name.

When the evidence is thin or the name is new to a recurring meeting, leave a note. Put the evidence in its `--why`, with Segment handles:

- `suggest-name M SPEAKER NAME --at #N --why "..."` proposes a name; `#N` is the Segment that is the evidence. Accepting it also saves the Voice Profile.
- `suggest-merge M SOURCE TARGET --at #N --why "..."` and `suggest-move M #N SPEAKER|new:NAME --why "..."` propose a merge or a move you cannot prove.
- `ask M #N "..."` asks when you have no proposal; the samples and timestamps are the user's clue.

`rename M SPEAKER NAME` applies a name the transcript proves. Add `--save-profile` only for a name the user confirmed (an accepted note already did): it makes future Meetings name that voice automatically.

**Done** when `speakers M --unnamed` is empty, or each remaining Speaker has a Review Note.

## 4. Review

`suspects M` prints up to four sections. For each hit, `show M --from T --to T` reads the passage in context (a filtered `show` prints Segments only), and `words M --from T --to T --below 0.6` shows the Words as heard. To find a name, number or term, `show M --grep PATTERN` (case-insensitive regex; combines with `--speaker`, `--from`, `--to`).

| Section | Reading |
|---|---|
| REPEATED | The same sentence back to back is a Transcriber filling silence. Report the time range; the text is not yours to fix. |
| LOW-CONFIDENCE PASSAGES (worst first) | Segments holding Words under 0.4, each line ending `weak: word 0.14, ...`. Start at the top; a very low Word inside a name or term is the likeliest error. |
| CORRECTED BY VOCABULARY | Check each `heard->term` fix against the context. |
| SENTENCE CUT BY A SPEAKER CHANGE | A sentence that continues across two Speakers: the Diarizer usually moved the boundary by a few Words. Read the pair in context (show --from --to). If the text proves who finishes or starts the sentence, assign the short side to that Speaker; when the cut falls inside a line, split it. Otherwise suggest-move. A real interruption stays as it is. |

Read the transcript yourself for two failures no command finds: a side conversation an open mic captured (a long off-topic block from someone who barely speaks otherwise) and plausible-sounding numbers. Leave an implausible number as `note M #N "..."`; the number stays as transcribed.

Fix a passage with `edit M #N "text"` only when the transcript supports the fix: a term in the vocabulary or participants, the same word spelled right elsewhere, or an obvious grammar mishearing in context. For a fix the transcript does not prove, `suggest M #N "text" --why "..."` leaves the proposed text for the user to accept. With no candidate text, `ask M #N "..."`.

**Done** when every `suspects` entry is fixed, left as a Review Note, judged a real interruption, or (a REPEATED range) reported to the user.

## 5. Hand off

Report what you named and what you edited (Segment handles) in a short summary. Tell the user how many notes are open (`notes M --status open`) and that they accept or answer them on the Meeting page. For a meeting record, `export M --format json --out FILE` feeds the user's minutes workflow, if they have one; this skill ends at a reviewed transcript.

## Learning and undo

- Accepting a `suggest` on the page teaches Vocabulary, because the click is the user's confirmation. Prefer `suggest` to asking for confirmation in chat.
- `edit` teaches Vocabulary only with `--learn`, and a learned Misheard Form applies to every future Meeting. Pass `--learn` only for corrections the user confirmed.
- To teach a new term, first `edit --learn` changing only the misheard words, then fix the rest of the sentence in a second `edit` without `--learn`. Only a short phrase that looks like a term is learned: capitalized words, acronyms, or a term from the Meeting's vocabulary or participants. A whole-sentence rewrite or a fix to common words teaches nothing.
- `revert M #N` undoes a text edit.
- Names and reassignments survive `reprocess reidentify` and `reprocess reapply-vocabulary`. `reprocess rediarize` carries names by Turn overlap and drops reassignments, so warn the user before suggesting it. A processed dual-track Meeting cannot be re-diarized at all (the API answers 400, `reprocessable` is false): the app keeps only the mixed audio. A Split survives all three, but `split --speaker` is a reassignment, so `rediarize` drops that Speaker choice and keeps the cut.

## Line markers

`[edited]` text changed by hand, `[moved]` Speaker changed by hand, `[conf 0.41]` Segment confidence under 0.6, `[fixed: heard->term]` a Vocabulary Correction the user has not reviewed, `[confirmed: heard->term]` one the user confirmed.

## Commands

`health` · `list` · `upload` · `process` · `reprocess KIND` · `wait` · `show` · `speakers` · `words` · `suspects` · `rename` · `add-speaker` · `merge` · `edit` · `revert` · `assign` · `split` · `unsplit` · `notes` · `ask` · `note` · `suggest` · `suggest-name` · `suggest-move` · `suggest-split` · `suggest-merge` · `close` · `set` · `export`. Add `--json` before the command for the API's raw JSON.
