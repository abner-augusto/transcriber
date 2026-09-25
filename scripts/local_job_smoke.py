"""Run private local audio through the production LocalJobRunner without touching the user's DB."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker


PRESET_IDS = ("parakeet-tdt-0.6b-v3", "faster-whisper-large-v3")


def _gpu_memory_mib() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip().splitlines()[0]
    except Exception:
        return "unavailable"


def _shortest_available_audio() -> tuple[str, float]:
    from config import settings
    from database import SessionLocal
    from models import Meeting

    db = SessionLocal()
    try:
        rows = (
            db.query(Meeting.audio_filepath, Meeting.duration)
            .filter(Meeting.audio_filepath.is_not(None))
            .order_by(Meeting.duration.asc())
            .all()
        )
    finally:
        db.close()

    for audio_path, duration in rows:
        path = Path(audio_path)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if path.is_file():
            return str(path), float(duration or 0)
    raise RuntimeError("No existing local Meeting audio file was found")


def _run_smoke(audio_path: str, audio_duration: float) -> list[dict]:
    from config import settings
    from database import Base, configure_sqlite_engine
    from jobs import configure
    from jobs.runners import InProcessBus, LocalJobRunner
    import models
    from models import Job, Meeting, MeetingStatus
    from models.job import JobStatus, JobType
    from migrations.runner import upgrade

    import preferences

    original_hf_token = os.environ.get("HF_AUTH_TOKEN")
    original_database_url = os.environ.get("DATABASE_URL")
    original_storage_path = os.environ.get("STORAGE_PATH")
    token = preferences.hf_token()
    user_preferences = preferences.load()

    results = []
    with tempfile.TemporaryDirectory(prefix="transcriber-local-job-smoke-") as temp_root:
        temp_path = Path(temp_root)
        temp_storage = temp_path / "storage"
        temp_storage.mkdir()
        # Preserve non-secret user preferences for the real pipeline while
        # keeping the HF credential in process memory only.
        database_path = temp_path / "smoke.db"
        database_url = URL.create("sqlite", database=str(database_path)).render_as_string(
            hide_password=False
        )
        os.environ["DATABASE_URL"] = database_url
        os.environ["STORAGE_PATH"] = str(temp_storage)
        settings.database_url = database_url
        settings.storage_path = str(temp_storage)
        preferences.update(
            user_preferences.model_copy(update={"hf_auth_token": ""}).model_dump(mode="json"),
            storage_dir=temp_storage,
            legacy_preferences_path=temp_path / "no-legacy-file",
        )
        if token:
            os.environ["HF_AUTH_TOKEN"] = token

        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )
        configure_sqlite_engine(engine)
        Base.metadata.create_all(engine)
        upgrade(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        progress_bus = InProcessBus()
        runner = LocalJobRunner(progress_bus=progress_bus, session_factory=sessions)
        configure(runner=runner, progress_bus=progress_bus, session_factory=sessions)

        try:
            runner.start()
            for preset_id in PRESET_IDS:
                meeting_id = str(uuid.uuid4())
                with sessions() as db:
                    meeting = Meeting(
                        id=meeting_id,
                        title="Local runner smoke",
                        status=MeetingStatus.PROCESSING,
                        preset_id=preset_id,
                        audio_filepath=audio_path,
                        duration=audio_duration,
                    )
                    db.add(meeting)
                    db.flush()
                    job = Job(meeting_id=meeting_id, job_type=JobType.PROCESS_MEETING)
                    db.add(job)
                    db.commit()
                    job_id = job.id
                    runner.submit(job)

                started = time.monotonic()
                while time.monotonic() - started < 3600:
                    with sessions() as db:
                        job = db.get(Job, job_id)
                        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                            results.append({
                                "preset": preset_id,
                                "status": job.status.value,
                                "elapsed_seconds": round(time.monotonic() - started, 2),
                                "segments": db.query(models.Segment)
                                    .filter_by(meeting_id=meeting_id).count(),
                                "speakers": db.query(models.Speaker)
                                    .filter_by(meeting_id=meeting_id).count(),
                                "error_type": "none" if not job.error else job.error.split(":", 1)[0],
                            })
                            break
                    time.sleep(0.25)
                else:
                    results.append({"preset": preset_id, "status": "timeout"})

                if results[-1]["status"] != JobStatus.COMPLETED.value:
                    break
        finally:
            runner.stop()
            engine.dispose()
            if original_hf_token is None:
                os.environ.pop("HF_AUTH_TOKEN", None)
            else:
                os.environ["HF_AUTH_TOKEN"] = original_hf_token
            if original_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original_database_url
            if original_storage_path is None:
                os.environ.pop("STORAGE_PATH", None)
            else:
                os.environ["STORAGE_PATH"] = original_storage_path

    return results


def main() -> int:
    audio_path, duration = _shortest_available_audio()
    before = _gpu_memory_mib()
    print(f"AUDIO_DURATION_SECONDS={duration:.2f}")
    print(f"GPU_MEMORY_BEFORE_MIB={before}")
    results = _run_smoke(audio_path, duration)
    for result in results:
        print(result)
    print(f"GPU_MEMORY_AFTER_MIB={_gpu_memory_mib()}")
    return 0 if len(results) == len(PRESET_IDS) and all(
        item["status"] == "completed" for item in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
