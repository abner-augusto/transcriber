# Installation - Windows

## Quick install

```powershell
git clone https://github.com/fltman/transcriber.git
cd transcriber
powershell -ExecutionPolicy Bypass -File install.ps1   # Automated installer
powershell -ExecutionPolicy Bypass -File start.ps1     # Start all services
```

The script handles everything below automatically. Read on if you prefer manual setup or need to troubleshoot.

## Prerequisites

- **Windows 10/11** (64-bit)
- **Docker Desktop** for Windows
- **Python 3.11+** (from python.org, check "Add to PATH" during install)
- **Node.js 18+** (from nodejs.org)
- **FFmpeg** (see step below)
- **Git** (from git-scm.com)
- **CMake** (from cmake.org, or via Visual Studio)
- **Visual Studio 2022** with "Desktop development with C++" workload (for compiling whisper.cpp)
- **Ollama** for Windows, or an OpenRouter API key
- **Hugging Face account** with access to pyannote/speaker-diarization-3.1

### Optional: NVIDIA GPU acceleration

If you have an NVIDIA GPU with CUDA support, whisper.cpp can use it for faster transcription. Install the [CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit) before building whisper.cpp.

## Installation

### 1. Clone the repo

```powershell
git clone https://github.com/fltman/transcriber.git
cd transcriber
```

### 2. Install FFmpeg

Download from https://www.gyan.dev/ffmpeg/builds/ (get the "essentials" build), extract it, and add the `bin` folder to your system PATH.

Verify it works:

```powershell
ffmpeg -version
```

### 3. Build whisper.cpp

```powershell
git clone https://github.com/ggerganov/whisper.cpp.git ..\whisper.cpp
cd ..\whisper.cpp

# CPU only
cmake -B build
cmake --build build --config Release

# OR with CUDA (if you have an NVIDIA GPU)
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release

cd ..\transcriber
```

The binary will be at `..\whisper.cpp\build\bin\Release\whisper-cli.exe`.

#### DTW Timestamps in whisper.cpp
whisper.cpp natively supports Dynamic Time Warping (`-dtw <preset>`) for precise token/word timestamps.
- Check support with: `..\whisper.cpp\build\bin\Release\whisper-cli.exe --help` (look for `-dtw MODEL`).
- Transcriber automatically detects the model preset (e.g. `large.v3.turbo`, `medium`, `small`, `base`, `tiny`) and passes `-dtw <preset> -nfa`.
- If DTW is unsupported on an older build, it gracefully falls back to standard token timestamps with a warning in the logs.

### 4. Download Whisper models

```powershell
mkdir models

# Medium model (main transcription, higher quality)
curl -L -o models\kb_whisper_ggml_medium.bin https://huggingface.co/KBLab/kb-whisper-medium/resolve/main/ggml-model.bin

# Small model (live transcription, faster)
curl -L -o models\kb_whisper_ggml_small.bin https://huggingface.co/KBLab/kb-whisper-small/resolve/main/ggml-model.bin
```

### 5. Start PostgreSQL and Redis

Make sure Docker Desktop is running, then:

```powershell
docker-compose up -d
```

This starts:
- PostgreSQL on port **5433**
- Redis on port **6380**

### 6. Create the .env file

Create a file named `.env` in the project root with this content:

```env
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

# Paths to whisper.cpp (adjust to your setup, use forward slashes)
WHISPER_CLI_PATH=../whisper.cpp/build/bin/Release/whisper-cli.exe
WHISPER_MODEL_PATH=./models/ggml-large-v3-turbo.bin
WHISPER_SMALL_MODEL_PATH=./models/ggml-small.bin

STORAGE_PATH=./storage

# Hugging Face token (needed for pyannote.audio speaker diarization)
# Get yours at https://huggingface.co/settings/tokens
# You must accept the model terms at https://huggingface.co/pyannote/speaker-diarization-3.1
HF_AUTH_TOKEN=hf_your_token_here
```

Edit the file and fill in your actual paths and tokens.

### 7. Set up the Python backend

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m pip check

foreach ($engine in @("qwen3-asr", "vibevoice")) {
    python -m venv "venv-engines\$engine"
    & "venv-engines\$engine\Scripts\python.exe" -m pip install torch==2.11.0 torchaudio==2.11.0
    & "venv-engines\$engine\Scripts\python.exe" -m pip install -r "requirements\engines\$engine.txt"
    & "venv-engines\$engine\Scripts\python.exe" -m engine_runtimes.manifest $engine --include-optional --presets-dir model_presets
}
```

**Note**: Installing PyTorch, pyannote.audio and SpeechBrain may take a while and download several GB of model files on first run.

If you have an NVIDIA GPU, install the CUDA version of PyTorch first:

```powershell
foreach ($engine in @("qwen3-asr", "vibevoice")) {
    & "venv-engines\$engine\Scripts\python.exe" -m pip install torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
    & "venv-engines\$engine\Scripts\python.exe" -m pip install -r "requirements\engines\$engine.txt"
}
```

The VibeVoice requirement uses an immutable source commit. Compatibility is
recorded in `engine_runtimes\manifests`. Validate model metadata after setting the
model path:

```powershell
venv-engines\qwen3-asr\Scripts\python.exe -m engine_runtimes.manifest qwen3-asr --checkpoint C:\path\to\Qwen3-ASR-1.7B-hf
venv-engines\vibevoice\Scripts\python.exe -m engine_runtimes.manifest vibevoice --checkpoint C:\path\to\VibeVoice-ASR-Streaming-7B
```

On a compatibility error, recreate the affected Engine runtime and reinstall its
requirement file. Qwen3-ASR uses Transformers 5.16.1 with native forced alignment;
VibeVoice uses Transformers 4.57.6, BitsAndBytes NF4, and proportional Word timestamps. Do not mix
their dependency sets.

### 8. Set up the frontend

```powershell
cd frontend
npm install
cd ..
```

### 9. Set up Ollama (if using local LLM)

Download and install Ollama from https://ollama.com, then:

```powershell
ollama pull qwen3:8b
```

## Running

Open **four separate terminals** (PowerShell or Command Prompt):

```powershell
# Terminal 1 - Backend API
venv\Scripts\activate
uvicorn main:app --port 8000 --reload

# Terminal 2 - Celery worker
venv\Scripts\activate
celery -A tasks.celery_app worker --loglevel=info --pool=solo

# Terminal 3 - Frontend
cd frontend
npm run dev

# Terminal 4 - Ollama (if using local LLM, skip if already running)
ollama serve
```

Open **http://localhost:5174** in your browser.

## Troubleshooting

### "No module named 'pyannote'" or torch errors
Make sure you activated the virtual environment (`venv\Scripts\activate`) before running.

### Celery won't start
On Windows, Celery requires the `--pool=solo` flag (which is already in the command above). The default prefork pool does not work on Windows.

### whisper-cli not found
Check that the path in your `.env` file points to the correct location. On Windows, the Release build goes into a `Release` subfolder.

### Docker containers won't start
Make sure Docker Desktop is running and WSL 2 is enabled. Check with `docker ps`.

### Slow first run
The first transcription downloads pyannote and SpeechBrain model files (several GB). Subsequent runs use cached models.

## Migrating from PostgreSQL to SQLite

Keep the PostgreSQL database and a `pg_dump` backup until you have opened the
SQLite database and confirmed the Meetings, transcripts, and search results.
The migration command refuses to overwrite its target and never writes to the
source database. Stop the app and worker first.

```powershell
docker compose exec postgres pg_dump -U transcriber -d transcriber -Fc -f /tmp/transcriber-before-sqlite.dump
docker compose cp postgres:/tmp/transcriber-before-sqlite.dump .\transcriber-before-sqlite.dump
.\venv\Scripts\python.exe -m scripts.migrate_to_sqlite --from "postgresql://transcriber:transcriber@localhost:5433/transcriber" --to .\storage\transcriber.db
```

Use the PostgreSQL URL from your `.env` if its credentials differ. The command
prints copied row counts and confirms the Segment text checksum for each
Meeting. If it reports a schema mismatch, checksum mismatch, or row-count
mismatch, stop and keep using the source database; do not point the app at the
partial `.migrating` file. After a successful report, change `DATABASE_URL` in
`.env` to `sqlite:///./storage/transcriber.db`, start the app, and verify your
Meetings and search before retiring PostgreSQL.
 enabled. Check with `docker ps`.

### Slow first run
The first transcription downloads pyannote and SpeechBrain model files (several GB). Subsequent runs use cached models.
