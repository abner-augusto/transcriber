# Linux and macOS installation

## Requirements

- Linux or macOS (64-bit)
- Python 3.11–3.14, Git, Node.js 18+, npm, CMake, FFmpeg, and `uv`
- A C++ compiler and build tools
- NVIDIA CUDA toolkit for GPU builds on Linux, or Apple Metal on macOS
- A Hugging Face account with access to pyannote/speaker-diarization-3.1

Install `uv` using the [official instructions](https://docs.astral.sh/uv/getting-started/installation/).

## Install and start

From the repository root:

```bash
chmod +x install.sh start.sh
./install.sh
```

The installer builds whisper.cpp and parakeet.cpp, installs the locked backend
dependencies, prepares isolated Engine environments, downloads the default
Parakeet model, and builds the frontend. Set `HF_AUTH_TOKEN` in `.env` to enable
speaker diarization. Accept the pyannote model terms before processing audio.

Start the app:

```bash
./start.sh
```

FastAPI, the Job runner, and the built UI use one Python process on port 8000.
For frontend development, run `npm run dev` from `frontend/`; Vite proxies API
requests to port 8000.

## Migrate an older PostgreSQL database

Stop the old app and worker, then retain a PostgreSQL dump. Install the
optional migration driver and follow the exact checks in
[the verification plan](plans/TEST-PLAN.md#plan-018-postgresql-to-sqlite). The
copy command never modifies its PostgreSQL source or overwrites its target.
Keep the database and dump until you open and search the migrated Meetings.

## Troubleshooting

- Install your distribution's compiler, CMake, and FFmpeg packages if a native
  Engine build fails.
- If CUDA is unavailable, the installer builds CPU versions of the native
  Engines.
- The first model use downloads several gigabytes. Later runs use local caches.
- Check `http://127.0.0.1:8000/api/health` for database and Engine status.
