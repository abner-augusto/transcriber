# Transcriber

AI-powered local meeting transcription with automatic speaker identification. Upload an audio file and get a full transcript with speakers identified by name.

![Stack](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Stack](https://img.shields.io/badge/React-61DAFB?style=flat&logo=react&logoColor=black)
![Stack](https://img.shields.io/badge/whisper.cpp-000?style=flat)
![Stack](https://img.shields.io/badge/pyannote.audio-orange?style=flat)

## How it works

1. **Upload** a recording through the web UI, optionally pinning the Preset to transcribe it with
2. **Audio extraction** — FFmpeg converts to 16 kHz mono WAV
3. **Transcription** — a **Transcriber** (whisper.cpp or parakeet.cpp) turns the audio into **Words**
4. **Diarization** — a **Diarizer** (pyannote or Nemotron 3 Diarization, chosen in Settings → Diarization, on the local GPU) turns the same audio into **Turns**
5. **Segments** — Words and Turns are combined into the paragraphs you read. Because the currency is
   the Word, a speaker who cuts in mid-sentence lands on their own line
6. **Speaker naming** — every Speaker starts as "Participant N"; a saved **Voice Profile** whose
   SpeechBrain embedding matches overrides that with a real name
7. **Results** — colour-coded transcript synced to audio playback, editable segments, export

Everything runs on this machine. No audio, transcript or voice embedding is ever sent anywhere —
see [ADR-0001](docs/adr/0001-no-data-leaves-the-machine.md). Terms in bold are defined in
[GLOSSARY.md](GLOSSARY.md).

## Swapping the transcription engine

The pipeline talks to two ports — `Transcriber` and `Diarizer` (`engines/ports.py`) — so a new model
is an adapter, not a rewrite. Nothing in `tasks/` changes.

```bash
# Compare the engines you have on the audio you actually care about
python bench/compare_engines.py test.mp3
```

To add an Engine: write an adapter in `engines/` that returns `list[Word]`, register it in
`engines/__init__.py`, and drop a Preset JSON in `model_presets/`:

```json
{
  "id": "parakeet-tdt-0.6b-v3",
  "name": "Parakeet TDT 0.6B v3",
  "engine": "parakeet.cpp",
  "model_path": "./models/parakeet/tdt-0.6b-v3-q8_0.gguf",
  "decoder": "tdt"
}
```

Pick the default in Settings → Presets, or pin one per Meeting at upload to A/B two Engines on the
same audio. A Preset whose binary or model file is missing is shown as unavailable rather than
failing a Job in the worker.

## Architecture

```
Browser ─── FastAPI ─── SQLite + FTS5
               │
               ├── in-process Job queue
               ├── spawned child process per Job
               └── built React UI + WebSocket progress
```

FastAPI, the local Job runner, and the built frontend use one application
process and one port. A child process handles each Job so model memory is
released when the Job ends. Vite remains available for frontend development.

## Platform guides

For platform-specific prerequisites and troubleshooting:
- [Windows installation guide](INSTALL_WINDOWS.md)
- [Linux installation guide](INSTALL_LINUX.md)

## Prerequisites

- Windows 10/11, Linux, or macOS
- Python 3.11–3.14, `uv`, Node.js 18+, npm, CMake, FFmpeg, Git, and a C++ toolchain
- NVIDIA CUDA or Apple Metal for GPU acceleration (optional)
- Hugging Face access to `pyannote/speaker-diarization-3.1` for diarization

## Quick install

```bash
git clone https://github.com/fltman/transcriber.git
cd transcriber
./install.sh
./start.sh
```

On Windows, use `install.ps1` and `start.ps1` instead.

The installer builds whisper.cpp and parakeet.cpp, installs the locked Python
dependencies and isolated Engine environments, downloads the default Parakeet
model, builds the frontend, and creates `.env`. Add `HF_AUTH_TOKEN` there if
speaker diarization is needed. The app opens at <http://127.0.0.1:8000>.

For frontend development, run `npm run dev` in `frontend/`; Vite proxies API
requests to port 8000.

## Migrate an older PostgreSQL database

For existing PostgreSQL data, retain a database dump and follow the migration
and verification steps in [plans/TEST-PLAN.md](plans/TEST-PLAN.md#plan-018-postgresql-to-sqlite).
The importer reads the source without changing it and refuses to overwrite its
SQLite target. Keep the dump until the migrated Meetings open and search works.

## Tests and release checks

The consolidated backend, frontend, migration, local-model, and clean-install
checks are in [plans/TEST-PLAN.md](plans/TEST-PLAN.md).

## Usage

1. Click **New transcription** on the home page
2. Choose **Single file** or **Dual-track / OBS**
   - **Single file**: drag-and-drop or browse for an audio/video file
   - **Dual-track / OBS**: provide a microphone track and an optional system-audio track
3. Enter a title and click **Start**
4. For uploaded files, click **Start transcription** on the meeting page
5. Watch real-time progress as the pipeline runs
6. Browse the transcript with synced audio playback
7. Click speaker names to rename, click segments to edit text
8. Settle **Review Notes** in the sidebar's Review tab: answer the agent's questions, accept or dismiss its suggestions, or leave a note on a segment (hover → Note). Segments with a note are tinted and the audio bar shows one clickable mark per note, amber when it waits for you and blue when it waits for the agent. Below the notes, **Vocabulary Corrections** lists every Word the Vocabulary changed in the Meeting (cyan underline in the transcript until confirmed), with Confirm and Undo per row
9. **Export** to SRT, WebVTT, TXT, Markdown, JSON, DOCX, or PDF

**Storage.** The app does not archive your recordings: keep the originals in the meeting's project folder. When a Meeting finishes processing, the app deletes the uploaded file(s) and the intermediate tracks and keeps only `audio.wav` (16 kHz mono; a mix for a dual-track Meeting) for playback and re-runs. A Meeting that has not finished processing keeps its upload. A processed dual-track Meeting cannot be re-diarized, fully reprocessed or duplicated, because those need the separate mic and system tracks ([ADR-0011](docs/adr/0011-the-app-keeps-no-original-recordings.md)).

## Command line

`transcriber_cli` runs and reads Meetings from a terminal, for scripting and for a coding agent that operates the app ([ADR-0010](docs/adr/0010-an-agent-may-operate-the-local-api.md)). It uses only the standard library, talks to the running app over HTTP (`http://127.0.0.1:8000`, or `$TRANSCRIBER_URL`), and prints one compact line per Segment. `--help` lists the commands.

```
uv run python -m transcriber_cli list
uv run python -m transcriber_cli upload reuniao.m4a --title "Obra 12/10" --participants "Ana, Bruno" --process --wait
uv run python -m transcriber_cli show <id> --from 10:00 --to 15:00
uv run python -m transcriber_cli show <id> --grep "Lourdes"
uv run python -m transcriber_cli speakers <id> --unnamed
uv run python -m transcriber_cli rename <id> SPEAKER_01 "Maria"
uv run python -m transcriber_cli edit <id> '#142' "Garrah confirmou"
uv run python -m transcriber_cli split <id> '#142' --before "Quem manda" --speaker "Maria"
uv run python -m transcriber_cli unsplit <id> '#142'
uv run python -m transcriber_cli suspects <id>
uv run python -m transcriber_cli notes <id> --status open
uv run python -m transcriber_cli suggest <id> '#142' "Garrah confirmou" --why "o nome da obra"
uv run python -m transcriber_cli suggest-split <id> '#142' --before "Quem manda" --speaker "Maria" --why "pergunta e resposta"
```

`<id>` is a Meeting's full id, a unique prefix of 4+ characters, or its exact title. A full id is fetched directly; a prefix or a title first reads the Meeting list.

An edit from the command line teaches Vocabulary only with `--learn`; an agent cannot hear the audio, so its corrections are guesses until you confirm them.

`split` cuts a Segment the Diarizer joined (two people on one line) at a Word, by time (`--at`) or by the first Word(s) of the second half (`--before`). The Meeting keeps the cut, so it survives every Reprocessing, Re-diarize included; `unsplit` takes it back. Later Segment handles (`#N`) shift by one. When the text alone does not show the cut, `suggest-split` takes the same arguments and leaves it as a Review Note; accepting the note on the Review tab runs the `split`.

## Project structure

```
transcriber/
├── GLOSSARY.md                 # Domain glossary — read this first
├── docs/adr/                  # Why things are the way they are
├── main.py                    # FastAPI app entry point
├── config.py                  # Pydantic settings (engine binaries, paths)
├── database.py                # SQLAlchemy + migrations
├── presets.py                 # Presets: which Engine + model to transcribe with
├── model_presets/             # One JSON file per Preset
├── migrations/                # Hand-run SQL, newest last
├── engines/                   # ← the swappable half
│   ├── ports.py               # Word, Turn, Transcriber, Diarizer
│   ├── whisper_cpp.py         # Transcriber: whisper-cli
│   ├── parakeet_cpp.py        # Transcriber: parakeet-cli
│   ├── pyannote.py            # Diarizer: pyannote (local GPU)
│   └── __init__.py            # Engine name -> adapter
├── api/
│   ├── meetings.py            # Upload, CRUD, process
│   ├── speakers.py            # Rename, merge speakers
│   ├── segments.py            # Edit transcript text
│   ├── export.py              # Multi-format export
│   └── model_settings.py      # Preset API
├── services/
│   ├── audio_retention.py     # Drops the raw sources once a Meeting is processed
│   ├── audio_service.py       # FFmpeg extraction
│   ├── embedding_service.py   # SpeechBrain ECAPA-TDNN
│   └── speaker_id_service.py  # Speaker Namer: Participant N + Voice Profiles
├── tasks/
│   ├── runners.py             # In-process progress bus and local Job runner
│   ├── process_meeting.py     # Main pipeline
│   ├── reprocess_task.py      # Re-diarize / re-identify
│   └── shared.py              # build_segments: Words + Turns -> Segments
├── models/                    # SQLAlchemy models
│   ├── meeting.py
│   ├── speaker.py
│   ├── segment.py
│   └── job.py
├── transcriber_cli/           # Stdlib command-line client of the HTTP API (ADR-0010)
├── tests/                     # pytest; fake Engines, no GPU needed
├── bench/
│   └── compare_engines.py     # Run every Preset over the same audio
└── frontend/                  # React + TypeScript
    └── src/
        ├── App.tsx
        ├── store.ts           # Zustand state
        ├── pages/
        │   ├── HomePage.tsx
        │   └── MeetingPage.tsx
        ├── components/
        │   ├── TranscriptView.tsx
        │   ├── SpeakerPanel.tsx
        │   ├── AudioPlayer.tsx
        │   ├── AudioSourceSelect.tsx
        │   ├── ProgressTracker.tsx
        │   ├── ExportDialog.tsx
        │   ├── EncryptDialog.tsx
        │   ├── DecryptDialog.tsx
        │   └── SettingsDialog.tsx
```

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand |
| Backend | FastAPI, SQLAlchemy, SQLite, local Job runner |
| Transcription | parakeet.cpp, faster-whisper, and optional local Engines |
| Diarization | pyannote.audio |
| Voice embeddings | SpeechBrain ECAPA-TDNN |
| Search | SQLite FTS5 with accent-insensitive matching |
| Runtime | `uv` locked Python dependencies and one FastAPI process |
| Media | FFmpeg |

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/meetings` | Upload audio file |
| `GET` | `/api/meetings` | List meetings |
| `GET` | `/api/meetings/{id}` | Get meeting with transcript |
| `DELETE` | `/api/meetings/{id}` | Delete meeting |
| `POST` | `/api/meetings/{id}/process` | Start transcription pipeline |
| `GET` | `/api/meetings/{id}/audio` | Stream audio |
| `GET` | `/api/meetings/{id}/export?format=srt` | Export transcript |
| `GET` | `/api/meetings/{id}/words?start=&end=` | Words as the Transcriber heard them, before Vocabulary Correction; `start`/`end` (seconds) keep the Words overlapping that range |
| `PUT` | `/api/segments/{id}` | Edit segment text; `learn: false` does not teach Vocabulary from the edit, and an edit teaches only phrases that look like a term (capitalized, an acronym, or named in the Meeting's Vocabulary or participants) |
| `POST` | `/api/segments/{id}/revert` | Undo a manual edit, restoring the derived text (teaches nothing) |
| `POST` | `/api/segments/{id}/corrections/confirm` | Accept a Vocabulary Correction (`start` identifies it): teaches its heard form as a Misheard Form of the term and marks that form confirmed (a form learned from an edit corrects after two sightings but stays up for review until then). 409 for an edited Segment or an unknown `start` |
| `POST` | `/api/segments/{id}/corrections/reject` | Undo a Vocabulary Correction: restores the heard text and records a Rejected Form, so that form never becomes that term again in any Meeting. Same 409s, and 409 for a Correction stored before offsets existed (reapply Vocabulary first) |
| `GET` | `/api/vocabulary/rejected-forms` | List Rejected Forms, newest first |
| `DELETE` | `/api/vocabulary/rejected-forms/{id}` | Remove a Rejected Form; the next Reprocessing corrects that form again |
| `PUT` | `/api/segments/{id}/speaker` | Move a Segment to another Speaker of the same Meeting |
| `POST` | `/api/segments/{id}/split` | Cut a Segment in two at the Word start nearest `at`; optional `speaker_id` for the second half. The cut is stored on the Meeting as a Split and survives every Reprocessing. Refused for an edited Segment |
| `POST` | `/api/segments/{id}/unsplit` | Join a Segment with the next one when a Split lies between them, and drop the Split |
| `PUT` | `/api/speakers/{id}` | Rename/recolor speaker |
| `POST` | `/api/meetings/{id}/speakers` | Add a Speaker the Diarizer missed (`display_name`; label `MANUAL_<n>`) |
| `POST` | `/api/speakers/merge` | Merge two speakers |
| `POST` | `/api/meetings/{id}/notes` | Leave a Review Note at a time range (`kind`: `comment`, `question`, `text`, `speaker_name`, `speaker_move`, `speaker_merge`, `split`; `author`: `agent` or `user`, and a `user` note is a `comment`) |
| `GET` | `/api/meetings/{id}/notes?status=` | List a Meeting's Review Notes (`open`, `answered`, `resolved`, `all`) |
| `POST` | `/api/notes/{id}/answer` | Answer an open question |
| `POST` | `/api/notes/{id}/done` | Close an answered question or an open comment (optional `reply`) |
| `POST` | `/api/notes/{id}/dismiss` | Dismiss an open suggestion or question, or an answered question |
| `POST` | `/api/notes/{id}/accept` | Apply an open suggestion through the existing edit routes; `learn: false` teaches no Vocabulary, `save_profile: false` skips the Voice Profile |
| `POST` | `/api/meetings/{id}/rediarize` | Re-run speaker diarization (400 for a dual-track Meeting that no longer has its tracks; `GET /api/meetings/{id}` says so with `reprocessable: false`) |
| `POST` | `/api/meetings/{id}/reidentify` | Re-identify speakers |
| `POST` | `/api/meetings/{id}/reapply-vocabulary` | Reapply vocabulary corrections |
| `GET` | `/api/search?q=...` | Search transcript segments |
| `GET` | `/api/meetings/{id}/analytics` | Get meeting analytics |
| `GET` | `/api/model-settings/presets` | List model presets |
| `GET` | `/api/model-settings/assignments` | Get model assignments |
| `PUT` | `/api/model-settings/assignments` | Update model assignments |
| `WS` | `/ws/meetings/{id}` | Progress updates, and `{"type": "meeting_changed"}` when a Segment, Speaker or the Meeting's details are edited, so an open page refetches |

## Author

**Anders Bjarby**
- Web: [anders.bjarby.com](https://anders.bjarby.com)
- Email: [anders@brattoo.com](mailto:anders@brattoo.com)

## License

MIT
