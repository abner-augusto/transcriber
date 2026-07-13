# Transcriber

AI-powered local meeting transcription with automatic speaker identification. Upload an audio file, record in the browser, or run a live session - and get a full transcript with speakers identified by name.

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
Browser ─── React/Vite ──┐
                         ├── FastAPI ─── Celery Worker ─── whisper.cpp (Metal GPU)
                         │      │              │
                         │   WebSocket     pyannote.audio
                         │   (progress)    SpeechBrain
                         │      │           LLM (Ollama/OpenRouter)
                         │      │
                     PostgreSQL  Redis
                      (data)   (queue + pubsub)
```

**Hybrid setup**: PostgreSQL and Redis run in Docker. Python backend and Celery worker run natively on macOS for Metal GPU access.

## Platform guides

The instructions below are for **macOS with Apple Silicon**. For other platforms:
- [Windows installation guide](INSTALL_WINDOWS.md)
- [Linux installation guide](INSTALL_LINUX.md)

## Prerequisites

- **macOS** with Apple Silicon (for Metal GPU acceleration)
- **Docker** and **Docker Compose**
- **Python 3.11+**
- **Node.js 18+**
- **FFmpeg** (`brew install ffmpeg`)
- **whisper.cpp** compiled with Metal support
- **Ollama** with a model like `qwen3:8b` (recommended), or an OpenRouter API key
- **Hugging Face token** with access to `pyannote/speaker-diarization-3.1`

## Quick install

```bash
git clone https://github.com/fltman/transcriber.git
cd transcriber
bash install.sh   # macOS/Linux automated installer
bash start.sh     # Start all services
```

On Windows, use `install.ps1` and `start.ps1` instead (see [Windows guide](INSTALL_WINDOWS.md)).

The installer checks prerequisites, builds whisper.cpp, downloads models, sets up Python/Node dependencies, starts Docker, and creates the `.env` file. You only need to add your Hugging Face token afterwards.

## Manual installation

### 1. Clone the repo

```bash
git clone https://github.com/fltman/transcriber.git
cd transcriber
```

### 2. Build whisper.cpp with Metal support

```bash
git clone https://github.com/ggerganov/whisper.cpp.git ../whisper.cpp
cd ../whisper.cpp
cmake -B build -DWHISPER_METAL=ON
cmake --build build --config Release
cd ../transcriber
```

### 3. Download Whisper models

Download the KB-LAB Swedish GGML models:

```bash
mkdir -p models
# Medium model (main transcription, higher quality)
curl -L -o models/kb_whisper_ggml_medium.bin \
  https://huggingface.co/KBLab/kb-whisper-medium/resolve/main/ggml-model.bin

# Small model (live transcription, faster)
curl -L -o models/kb_whisper_ggml_small.bin \
  https://huggingface.co/KBLab/kb-whisper-small/resolve/main/ggml-model.bin
```

### 4. Start PostgreSQL and Redis

```bash
docker-compose up -d
```

This starts:
- PostgreSQL on port **5433**
- Redis on port **6380**

### 5. Create the .env file

```bash
cat > .env << 'EOF'
DATABASE_URL=postgresql://transcriber:transcriber@localhost:5433/transcriber
REDIS_URL=redis://localhost:6380/0

# LLM provider: "ollama" or "openrouter"
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# Alternative: OpenRouter (uncomment and fill in)
# LLM_PROVIDER=openrouter
# OPENROUTER_API_KEY=your_key_here
# OPENROUTER_MODEL=anthropic/claude-sonnet-4

# Paths to whisper.cpp (adjust to your setup)
WHISPER_CLI_PATH=../whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL_PATH=./models/kb_whisper_ggml_medium.bin
WHISPER_SMALL_MODEL_PATH=./models/kb_whisper_ggml_small.bin

STORAGE_PATH=./storage

# Hugging Face token (needed for pyannote.audio speaker diarization)
# Get yours at https://huggingface.co/settings/tokens
# You must accept the model terms at https://huggingface.co/pyannote/speaker-diarization-3.1
HF_AUTH_TOKEN=hf_your_token_here
EOF
```

Edit the file and fill in your actual paths and tokens.

### 6. Set up the Python backend

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 7. Set up the frontend

```bash
cd frontend
npm install
cd ..
```

### 8. Set up Ollama (if using local LLM)

```bash
# Install Ollama from https://ollama.com
ollama pull qwen3:8b
```

## Running

Start all services. You need **four terminals** (or use `&` to background them):

```bash
# Terminal 1 - Backend API
source venv/bin/activate
uvicorn main:app --port 8000 --reload

# Terminal 2 - Celery worker (background processing)
source venv/bin/activate
celery -A tasks.celery_app worker --loglevel=info --pool=solo

# Terminal 3 - Frontend
cd frontend
npm run dev

# Terminal 4 - Ollama (if using local LLM)
ollama serve
```

Open **http://localhost:5174** in your browser.

## Usage

1. Click **New transcription** on the home page
2. Choose **Upload**, **Record**, or **Live**
   - **Upload**: drag-and-drop or browse for an audio/video file
   - **Record**: select your microphone (or system audio) and record
   - **Live**: start a real-time transcription session
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
│   ├── celery_app.py          # Celery config
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
        │   ├── LiveRecordingBar.tsx
        │   └── SettingsDialog.tsx
        └── hooks/
            └── useLiveRecording.ts
```

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand |
| Backend | FastAPI, SQLAlchemy, Celery |
| Transcription | whisper.cpp with KB-LAB Swedish models |
| Diarization | pyannote.audio 3.1 |
| Voice embeddings | SpeechBrain ECAPA-TDNN |
| LLM | Ollama (qwen3:8b) or OpenRouter (Claude Sonnet 4) |
| Infrastructure | PostgreSQL, Redis, Docker Compose |
| Media | FFmpeg |

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/meetings` | Upload audio file |
| `POST` | `/api/meetings/live` | Create live session |
| `GET` | `/api/meetings` | List meetings |
| `GET` | `/api/meetings/{id}` | Get meeting with transcript |
| `DELETE` | `/api/meetings/{id}` | Delete meeting |
| `POST` | `/api/meetings/{id}/process` | Start transcription pipeline |
| `GET` | `/api/meetings/{id}/audio` | Stream audio |
| `GET` | `/api/meetings/{id}/export?format=srt` | Export transcript |
| `PUT` | `/api/segments/{id}` | Edit segment text |
| `PUT` | `/api/speakers/{id}` | Rename/recolor speaker |
| `POST` | `/api/speakers/merge` | Merge two speakers |
| `GET` | `/api/actions` | List actions |
| `POST` | `/api/actions` | Create custom action |
| `POST` | `/api/actions/{id}/run` | Run action on meeting |
| `GET` | `/api/actions/results/{id}/export` | Export action result |
| `POST` | `/api/meetings/{id}/encrypt` | Encrypt meeting |
| `POST` | `/api/meetings/{id}/decrypt` | Decrypt meeting |
| `GET` | `/api/model-settings/presets` | List model presets |
| `GET` | `/api/model-settings/assignments` | Get model assignments |
| `PUT` | `/api/model-settings/assignments` | Update model assignments |
| `WS` | `/ws/meetings/{id}` | Progress updates |
| `WS` | `/ws/live/{id}` | Live transcription stream |

## Author

**Anders Bjarby**
- Web: [anders.bjarby.com](https://anders.bjarby.com)
- Email: [anders@brattoo.com](mailto:anders@brattoo.com)

## License

MIT
