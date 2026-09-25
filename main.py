import shutil
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings as _settings
from database import init_db, cleanup_orphaned_storage, get_db, engine
from models import Meeting
from api import meetings, speakers, segments, export, websocket, model_settings, search, speaker_profiles, vocabulary, analytics, preferences

app = FastAPI(title="Transcriber")

_default_origins = ["http://localhost:5174", "http://localhost:5175", "http://127.0.0.1:5174", "http://127.0.0.1:5175"]
_cors_origins = [x.strip() for x in _settings.cors_origins.split(",") if x.strip()] if _settings.cors_origins else _default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(meetings.router)
app.include_router(speakers.router)
app.include_router(segments.router)
app.include_router(export.router)
app.include_router(websocket.router)
app.include_router(model_settings.router)
app.include_router(search.router)
app.include_router(speaker_profiles.router)
app.include_router(vocabulary.router)
app.include_router(analytics.router)
app.include_router(preferences.router)

_frontend_dist = Path(__file__).parent / "frontend" / "dist"
# Paths under these prefixes name a route or a file; they never fall back to the UI.
_NOT_CLIENT_ROUTES = ("api/", "assets/")


@app.on_event("startup")
def startup():
    init_db()
    from jobs import configure, recover
    from jobs.runners import InProcessBus, LocalJobRunner

    progress_bus = InProcessBus()
    runner = LocalJobRunner(progress_bus=progress_bus)
    configure(runner=runner, progress_bus=progress_bus)
    # RUNNING work is interrupted by an app restart; PENDING work is resumed
    # by the local runner in creation order.
    recover()
    cleanup_orphaned_storage()
    runner.start()
    app.state.local_job_runner = runner
    import logging
    _log = logging.getLogger(__name__)
    from preferences import hf_token
    token = hf_token()
    if not token or token == "hf_your_token_here":
        _log.warning("HF_AUTH_TOKEN not set — speaker diarization will fail. "
                     "Set it in .env (get one at https://huggingface.co/settings/tokens)")


@app.get("/api/meetings/{meeting_id}/audio")
def stream_audio(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting or not meeting.audio_filepath:
        raise HTTPException(404, "Audio not found")

    path = Path(meeting.audio_filepath)
    if not path.exists():
        raise HTTPException(404, "Audio file not found")

    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Accept-Ranges": "bytes"},
    )


@app.get("/api/health")
def health():
    checks = {}

    # Database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Whisper CLI
    whisper_path = Path(_settings.whisper_cli_path)
    checks["whisper_cli"] = "ok" if whisper_path.exists() else f"missing: {whisper_path}"

    # Disk space
    storage_path = Path(_settings.storage_path)
    storage_path.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(storage_path)
    free_gb = disk.free / (1024 ** 3)
    checks["disk_free_gb"] = round(free_gb, 1)
    if free_gb < 1:
        checks["disk"] = "warning: less than 1 GB free"

    all_ok = all(
        v == "ok" for k, v in checks.items()
        if k not in ("disk_free_gb",)
    )
    return {"status": "ok" if all_ok else "degraded", **checks}


@app.on_event("shutdown")
def shutdown():
    runner = getattr(app.state, "local_job_runner", None)
    if runner is not None:
        runner.stop()
        del app.state.local_job_runner


@app.get("/api/settings")
def get_settings():
    from preferences import public, hf_token
    from engines import diarizer_status
    prefs = public()
    return {
        "preferences": prefs,
        "diarizers": [
            {"id": engine, "name": name, "description": description, **diarizer_status(engine, hf_token=hf_token())}
            for engine, name, description in (
                ("pyannote", "pyannote Community-1", "Community speaker diarization"),
                ("nemotron-3-diarization", "Nemotron 3 Diarization", "NVIDIA offline speaker diarization"),
            )
        ],
    }


@app.put("/api/settings/preferences")
def update_preferences(body: dict):
    from preferences import apply_preferences_request, public
    apply_preferences_request(body)
    return public()


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    """Serve the built frontend and route client-side URLs to its entrypoint."""
    if not _frontend_dist.is_dir():
        raise HTTPException(404, "Frontend build not found; run npm run build in frontend/")
    requested = (_frontend_dist / path).resolve()
    try:
        requested.relative_to(_frontend_dist.resolve())
    except ValueError:
        raise HTTPException(404, "Not found")
    if requested.is_file():
        return FileResponse(requested)
    if f"{path}/".startswith(_NOT_CLIENT_ROUTES):
        raise HTTPException(404, "Not found")
    return FileResponse(_frontend_dist / "index.html")

