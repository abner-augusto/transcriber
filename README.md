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
4. **Diarization** — a **Diarizer** (pyannote 3.1, on the local GPU) turns the same audio into **Turns**
5. **Segments** — Words and Turns are combined into the paragraphs you read. Because the currency is
   the Word, a speaker who cuts in mid-sentence lands on their own line
6. **Speaker naming** — every Speaker starts as "Participant N"; a saved **Voice Profile** whose
   SpeechBrain embedding matches overrides that with a real name
7. **Results** — colour-coded transcript synced to audio playback, editable segments, export

Everything runs on this machine. No audio, transcript or voice embedding is ever sent anywhere —
see [ADR-0001](docs/adr/0001-no-data-leaves-the-machine.md). Terms in bold are defined in
[CONTEXT.md](CONTEXT.md).

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
  "model_path": "./models/parakeet/tdt-0.6b-v3-q4_k.gguf",
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
8. Run **Actions** (summarize, action items, etc.) from the sidebar
9. **Export** to SRT, WebVTT, TXT, Markdown, JSON, DOCX, or PDF

## Project structure

```
transcriber/
├── CONTEXT.md                 # Domain glossary — read this first
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
        │   ├── ActionsPanel.tsx
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
| `PUT` | `/api/segments/{id}` | Edit segment text |
| `PUT` | `/api/speakers/{id}` | Rename/recolor speaker |
| `POST` | `/api/speakers/merge` | Merge two speakers |
| `POST` | `/api/meetings/{id}/rediarize` | Re-run speaker diarization |
| `POST` | `/api/meetings/{id}/reidentify` | Re-identify speakers |
| `POST` | `/api/meetings/{id}/reapply-vocabulary` | Reapply vocabulary corrections |
| `GET` | `/api/search?q=...` | Search transcript segments |
| `GET` | `/api/meetings/{id}/analytics` | Get meeting analytics |
| `GET` | `/api/model-settings/presets` | List model presets |
| `GET` | `/api/model-settings/assignments` | Get model assignments |
| `PUT` | `/api/model-settings/assignments` | Update model assignments |
| `WS` | `/ws/meetings/{id}` | Progress updates |

## Author

**Anders Bjarby**
- Web: [anders.bjarby.com](https://anders.bjarby.com)
- Email: [anders@brattoo.com](mailto:anders@brattoo.com)

## License

MIT
