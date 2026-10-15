# Transcriber

A local-only tool that turns a pre-recorded audio file of a conversation into a searchable,
speaker-attributed transcript. Everything runs on the user's machine; nothing is sent anywhere.

## Language

### The recording

**Meeting**:
A single recorded conversation brought to the tool as an audio file, together with everything
derived from it. The tool keeps only the audio it derived (`audio.wav`); the original recordings
live outside it (ADR-0011).
_Avoid_: session, recording, upload, call

**Source Reference**:
What the tool keeps of a Meeting's original recording, which lives outside it: the file's name, size
and a fast hash, plus the absolute path it was last seen at when the client knew it. A rerun that
needs the original (a dual-track Re-diarize, a Full reprocess, a Duplicate) reads it from that path,
or from a folder the user listed for searching (a few levels deep); a moved file is pointed at again, and must match the
hash. One per track: `mic` and `system`, or `audio` for a single file.
_Avoid_: source file, attachment, link

**Track Layout**:
What the tool found in a single uploaded file that carries more than one track, and which of them it
reads as the mic and the system. A track is a stream of the file (a stereo stream counts as one) or,
when the file's only stream is multi-channel, one of its channels. Each is sampled and judged
`speech`, `silent` (nothing recorded), `duplicate` (a copy of an earlier track, as in a fake stereo)
or `mix` (the sum of the others, as OBS track 1 can be). The mic and the system are chosen among
the `speech` tracks by the names the recorder gave them ("Microfone", "Computador"), else by file
order. The user can overrule the choice until the Meeting is processed.
_Avoid_: channel layout, stream map

**Vocabulary**:
Domain-specific words and names — supplied by the user or learned from their corrections — that
are given to the Transcriber so it spells them correctly. Vocabulary Correction also applies
them afterwards to Words it still got wrong.
_Avoid_: prompt, hints, glossary, dictionary

**Misheard Form**:
A way the Transcriber has been seen to get a Vocabulary term wrong ("Galo" for "Garrah"), learned
when the user corrects a Segment. Belongs to the term, not to one Meeting. Learned only from edits
whose new phrase looks like a term (capitalized or an acronym, or already named in the Meeting's
Vocabulary or participants). It corrects on its own after two sightings, but its Corrections stay
marked for review until the user confirms one of them.
_Avoid_: alias, typo, mapping

**Rejected Form**:
A heard form the user said is not a Misheard Form of a term ("Galo" is not "Garrah" here). Vocabulary
Correction never turns it into that term again, in any Meeting; the user can remove it later.
_Avoid_: exception, blocklist, stopword

**Vocabulary Correction**:
Replacing Words the Transcriber misheard with the Vocabulary term they were meant to be. Applied
when Segments are derived, so the Words stay as the Transcriber heard them and a Correction can
be re-applied without transcribing again. Records what it changed, where, and by which rule.
The user confirms or rejects each one on the Meeting page.
_Avoid_: autocorrect, post-processing, spell check

### What the transcript is made of

**Word**:
A single spoken word, with a start time, an end time, and a confidence. The smallest unit the
tool works in, and what a Transcriber produces.
_Avoid_: token

**Turn**:
A continuous stretch of audio attributed to one Speaker. What a Diarizer produces. A Turn knows
*when* someone spoke, never *what* they said.
_Avoid_: diarization segment, speaker segment

**Segment**:
A run of consecutive Words spoken by one Speaker. The unit the user reads, edits, exports, and
searches. Derived by combining Words with Turns — never produced directly by an Engine.
_Avoid_: line, utterance, caption, block

### Who is speaking

**Speaker**:
A distinct voice within one Meeting. Exists only inside the Meeting that contains it.
_Avoid_: participant (that is a default *name* for an unidentified Speaker, not the concept),
person, voice

**Voice Profile**:
A stored voice fingerprint of a known person, persisting across Meetings, used to recognise them
in a Meeting they haven't been named in yet. A Voice Profile is about a real person; a Speaker is
about one Meeting.
_Avoid_: speaker profile, enrollment, voiceprint, profile (bare — it collides with Preset)

### The things that do the work

**Transcriber**:
Turns a Meeting's audio into Words. Knows nothing about who is speaking.
_Avoid_: ASR, STT, whisper (that is one Engine, not the concept)

**Transcription**:
The immutable result of one Transcriber run: its Words, optional native Turns,
and Engine-owned provenance such as runtime diagnostics or the resolved DTW
preset. It does not include the Preset or other choices made by the user.
_Avoid_: transcript (the full Meeting artifact)

**Diarizer**:
Turns a Meeting's audio into Turns. Knows nothing about what was said.
_Avoid_: speaker segmentation, pyannote (that is one Engine)

**Speaker Namer**:
Assigns a name to each Speaker in a Meeting — by matching a Voice Profile, or by falling back to
"Participant N".
_Avoid_: speaker identification, speaker recognition

**Engine**:
A concrete local model-and-binary that satisfies a Transcriber or a Diarizer — whisper.cpp,
parakeet.cpp, pyannote. Engines are interchangeable; the rest of the tool does not know which one
ran.
_Avoid_: backend, provider, model (a model is what an Engine loads, not the Engine itself)

### Running it

**Preset**:
A named, user-editable configuration naming an Engine and the model it should load. Choosing a
Preset is how the user chooses an Engine.
_Avoid_: profile (collides with Voice Profile), config, settings

**Preferences**:
The user's saved choices that apply by default across Meetings, such as the default Preset,
Vocabulary, and whether to use Voice Profiles.
_Avoid_: settings (can mean machine configuration)

**RunConfig**:
The record of the Preferences and Preset that applied when a Job began running. It says which
choices that Job used, even if the user changes Preferences later.
_Avoid_: configuration snapshot, job settings

**Job**:
One unit of background processing over a single Meeting, carrying its own progress and status.
_Avoid_: task (that names the code a Job runs, not the Job itself)

**Reprocessing**:
Re-running diarization or speaker naming over a Meeting that has already been transcribed,
without transcribing it again — typically after saving a new Voice Profile. Re-applying
Vocabulary Correction is also available after changing the Meeting's Vocabulary.
Names the user gave Speakers survive it: by label when the Turns are kept, by Turn overlap when they are new.
_Avoid_: rerun, refresh

### Reviewing

**Review Note**:
A question, comment or suggestion anchored at a time range of a Meeting, left by the agent or the
user for the other to settle. Accepting a suggestion is the user's confirmation. It keeps its time
range through Reprocessing and is applied to the Segment at that range when it is accepted.
_Avoid_: comment (bare), annotation, flag

**Split**:
A boundary the user forces inside a Segment, at the start of a Word. The Meeting keeps it, so
every Reprocessing derives the Segments with that boundary; a Split survives even Re-diarize.
_Avoid_: cut, break
