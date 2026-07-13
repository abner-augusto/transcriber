# Transcriber

A local-only tool that turns a pre-recorded audio file of a conversation into a searchable,
speaker-attributed transcript. Everything runs on the user's machine; nothing is sent anywhere.

## Language

### The recording

**Meeting**:
A single recorded conversation brought to the tool as an audio file, together with everything
derived from it.
_Avoid_: session, recording, upload, call

**Vocabulary**:
Domain-specific words and names — supplied by the user or learned from their corrections — that
are given to the Transcriber so it spells them correctly.
_Avoid_: prompt, hints, glossary, dictionary

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

**Job**:
One unit of background processing over a single Meeting, carrying its own progress and status.
_Avoid_: task (reserved for the Celery mechanism that runs a Job)

**Reprocessing**:
Re-running diarization or speaker naming over a Meeting that has already been transcribed, without
transcribing it again — typically after saving a new Voice Profile.
_Avoid_: rerun, refresh
