import sys
from pathlib import Path

# Ensure project root is on sys.path so lazy imports (presets, engines, etc.) work.
#
# Celery only lends us the cwd: it imports the app named by -A inside
# celery.utils.imports.cwd_in_path(), which puts the cwd on sys.path and then
# takes it back off. Boot-time imports therefore resolve, but anything a task
# imports lazily — engines.pyannote, and preferences underneath it — would not.
#
# The insert must be unconditional. Celery's borrowed entry is still on sys.path
# while this runs, so a "not in sys.path" guard would skip the insert and leave
# nothing behind once celery removes it. Inserting a second copy is the point:
# sys.path.remove() drops only one, and ours outlives the context.
_project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _project_root)

from celery import Celery
from config import settings

celery_app = Celery(
    "transcriber",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["tasks.process_meeting", "tasks.reprocess_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_soft_time_limit=3300,  # 55 min soft limit (raises SoftTimeLimitExceeded)
    task_time_limit=3600,       # 60 min hard kill
    worker_prefetch_multiplier=1,
    result_expires=3600,
    worker_redirect_stdouts_level="INFO",
)
