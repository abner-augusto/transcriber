import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, defer

from pydantic import BaseModel

from sqlalchemy import func

import presets
from database import get_db
import jobs
from jobs import JobAlreadyRunning, MeetingNotFoundError
from models import Meeting, MeetingStatus, Speaker, Segment
from models.job import Job, JobType
from config import get_meeting_path
from services import source_reference
from services.audio_service import AudioService
from transcript.words import words_from_stored
from engines import probe_engine, diarizer_status

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

# Upload constraints
MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".mp4", ".m4a", ".webm", ".ogg", ".flac", ".aac", ".wma", ".mov", ".avi", ".mkv"}
MAX_TITLE_LENGTH = 500


def _require_usable_preset(preset: dict) -> dict:
    health = probe_engine(preset).to_dict()
    if health["state"] == "blocked":
        raise HTTPException(409, {"message": health["summary"], "health": health})
    return health


NO_TRACKS = (
    "This dual-track Meeting no longer has its mic and system tracks (the app keeps only "
    "the mixed audio once a Meeting is processed), so it cannot be {action}."
)


def _require_tracks(meeting: Meeting, action: str) -> None:
    if not meeting.reprocessable:
        raise HTTPException(400, NO_TRACKS.format(action=action))


def _share_file(src: Path, dest: Path) -> None:
    """Give ``dest`` the content of ``src`` without storing it twice.

    A hard link, so deleting either Meeting leaves the other intact; a copy where the
    filesystem cannot link.
    """
    try:
        os.link(src, dest)
    except OSError:
        shutil.copyfile(src, dest)


@router.get("")
def list_meetings(db: Session = Depends(get_db)):
    speaker_counts = (
        db.query(Speaker.meeting_id, func.count().label("count"))
        .group_by(Speaker.meeting_id)
        .subquery()
    )
    segment_counts = (
        db.query(Segment.meeting_id, func.count().label("count"))
        .group_by(Segment.meeting_id)
        .subquery()
    )
    rows = (
        db.query(
            Meeting,
            func.coalesce(speaker_counts.c.count, 0),
            func.coalesce(segment_counts.c.count, 0),
        )
        .outerjoin(speaker_counts, Meeting.id == speaker_counts.c.meeting_id)
        .outerjoin(segment_counts, Meeting.id == segment_counts.c.meeting_id)
        # The raw Engine output is megabytes per Meeting; the list never shows it.
        .options(
            defer(Meeting.raw_transcription),
            defer(Meeting.raw_diarization),
            defer(Meeting.split_times),
        )
        .order_by(Meeting.created_at.desc())
        .all()
    )
    return [m.to_dict(speaker_count=sc, segment_count=sgc) for m, sc, sgc in rows]


@router.post("")
async def create_meeting(
    title: str = Form(...),
    file: UploadFile = File(...),
    system_file: UploadFile = File(None),
    min_speakers: int = Form(None),
    max_speakers: int = Form(None),
    vocabulary: str = Form(None),
    participants: str = Form(None),
    preset_id: str = Form(None),
    source_path: str = Form(None),
    system_source_path: str = Form(None),
    db: Session = Depends(get_db),
):
    # Where the user keeps the originals (the CLI sends it; a browser cannot).
    for field in (source_path, system_source_path):
        if field and not os.path.isabs(field):
            raise HTTPException(400, f"source_path must be an absolute path, got '{field}'")

    # Validate title
    title = title.strip()[:MAX_TITLE_LENGTH]
    if not title:
        raise HTTPException(400, "Title is required")

    # Validate file extension
    filename = file.filename or "upload.mp4"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Sanitize filename — strip path components and special characters
    safe_filename = re.sub(r'[^\w.\-]', '_', Path(filename).name)

    # Validate speaker counts
    if min_speakers is not None and min_speakers < 1:
        raise HTTPException(400, "min_speakers must be at least 1")
    if max_speakers is not None and max_speakers < 1:
        raise HTTPException(400, "max_speakers must be at least 1")
    if min_speakers and max_speakers and min_speakers > max_speakers:
        raise HTTPException(400, "min_speakers cannot exceed max_speakers")

    # Pin the Preset only if one was chosen; NULL means "whatever the default is at
    # the time the Job runs".
    if preset_id and not presets.get_preset(preset_id):
        raise HTTPException(400, f"Unknown preset '{preset_id}'")

    # Use global default vocabulary if none provided
    from preferences import load
    effective_vocab = vocabulary.strip()[:2000] if vocabulary else None
    if not effective_vocab:
        default_vocab = load().default_vocabulary
        if default_vocab:
            effective_vocab = default_vocab

    meeting = Meeting(
        title=title,
        original_filename=safe_filename,
        status=MeetingStatus.UPLOADED,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        vocabulary=effective_vocab,
        participants=participants.strip()[:2000] if participants else None,
        preset_id=preset_id or None,
    )
    db.add(meeting)
    db.flush()

    meeting_dir = get_meeting_path(meeting.id)

    if system_file is not None:
        # Explicit dual-track: mic + system files.
        # Keep raw sources separate from the processed mic/system artifacts generated
        # by AudioService. This also avoids FFmpeg input/output path collisions.
        mic_path = await _save_upload(file, str(meeting_dir / f"mic_source{ext}"))
        system_path = await _save_upload(system_file, str(meeting_dir / f"system_source{ext}"))
        meeting.mic_audio_filepath = mic_path
        meeting.system_audio_filepath = system_path
        meeting.is_dual_track = True
        meeting.source_refs = {
            "mic": source_reference.reference(mic_path, path=source_path or None, name=safe_filename),
            "system": source_reference.reference(
                system_path, path=system_source_path or None,
                name=re.sub(r'[^\w.\-]', '_', Path(system_file.filename or "system").name),
            ),
        }
    else:
        # Single file: probe for stereo / multi-stream and split into dual-track if found.
        upload_path = await _save_upload(file, str(meeting_dir / f"original{ext}"))
        meeting.source_refs = {
            "audio": source_reference.reference(upload_path, path=source_path or None, name=safe_filename)
        }
        probe = AudioService().probe_audio(upload_path)
        if probe["stream_count"] >= 2 or probe["channels"] >= 2:
            meeting.mic_audio_filepath = upload_path
            meeting.system_audio_filepath = upload_path
            meeting.is_dual_track = True
        else:
            meeting.audio_filepath = upload_path

    db.commit()

    return meeting.to_dict()


async def _save_upload(file: UploadFile, path: str) -> str:
    """Stream an uploaded file to disk, enforcing the size limit."""
    total_size = 0
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE:
                f.close()
                Path(path).unlink(missing_ok=True)
                raise HTTPException(
                    413,
                    f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024**3)} GB",
                )
            f.write(chunk)
    return path


@router.get("/{meeting_id}")
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return meeting.to_dict(include_segments=True)


class UpdateMeetingRequest(BaseModel):
    title: str | None = None
    vocabulary: str | None = None
    participants: str | None = None


@router.put("/{meeting_id}")
def update_meeting(meeting_id: str, req: UpdateMeetingRequest, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    if req.title is not None:
        title = req.title.strip()[:MAX_TITLE_LENGTH]
        if not title:
            raise HTTPException(400, "Title is required")
        meeting.title = title

    if req.vocabulary is not None:
        trimmed_vocab = req.vocabulary.strip()[:2000]
        meeting.vocabulary = trimmed_vocab if trimmed_vocab else None

    if req.participants is not None:
        trimmed_participants = req.participants.strip()[:2000]
        meeting.participants = trimmed_participants if trimmed_participants else None

    db.commit()
    jobs.notify_meeting_changed(meeting.id)
    return meeting.to_dict()


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    # Clean up files
    meeting_dir = get_meeting_path(meeting_id)
    if meeting_dir.exists():
        shutil.rmtree(meeting_dir)

    db.delete(meeting)
    db.commit()
    return {"ok": True}


ALREADY_PROCESSING = "Meeting is already being processed"


def _enqueue(db: Session, meeting_id: str, kind: JobType) -> Job:
    try:
        return jobs.enqueue(db, meeting_id, kind)
    except MeetingNotFoundError:
        raise HTTPException(404, "Meeting not found")
    except JobAlreadyRunning:
        raise HTTPException(409, ALREADY_PROCESSING)


def _reject_processing(meeting: Meeting) -> None:
    """Refuse early, before the Preset health check, what the atomic claim in
    jobs.enqueue would refuse anyway, with the same answer."""
    if meeting.status == MeetingStatus.PROCESSING:
        raise HTTPException(409, ALREADY_PROCESSING)


def _require_usable_diarizer() -> dict:
    from preferences import load, hf_token
    health = diarizer_status(load().diarization.engine, hf_token=hf_token())
    if health["state"] == "blocked":
        raise HTTPException(409, {"message": health["summary"], "health": health})
    return health


@router.post("/{meeting_id}/process")
def start_processing(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    _reject_processing(meeting)
    _require_tracks(meeting, "processed again")

    preset = presets.resolve_preset(meeting.preset_id)
    health = _require_usable_preset(preset)
    _require_usable_diarizer()

    job = _enqueue(db, meeting.id, JobType.PROCESS_MEETING)
    return {**job.to_dict(), "engine_health": health}


class DuplicateMeetingRequest(BaseModel):
    preset_id: str


@router.post("/{meeting_id}/duplicate")
def duplicate_meeting(meeting_id: str, req: DuplicateMeetingRequest, db: Session = Depends(get_db)):
    """Give a new Meeting this Meeting's audio pinned to a different Preset, and process it.

    Lets an A/B comparison run without touching the original — the source Meeting keeps
    its own results untouched.
    """
    source = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not source:
        raise HTTPException(404, "Meeting not found")
    _require_tracks(source, "duplicated")
    audio = (
        [source.mic_audio_filepath, source.system_audio_filepath]
        if source.is_dual_track else [source.audio_filepath]
    )
    if not all(audio):
        raise HTTPException(400, "Meeting has no audio to duplicate")
    if not all(Path(path).exists() for path in audio):
        raise HTTPException(400, "The Meeting's audio file is missing on disk, so it cannot be duplicated.")

    preset = presets.get_preset(req.preset_id)
    if not preset:
        raise HTTPException(400, f"Unknown preset '{req.preset_id}'")
    health = _require_usable_preset(preset)
    _require_usable_diarizer()

    copy = Meeting(
        title=f"{source.title} (copy · {preset['name']})"[:MAX_TITLE_LENGTH],
        status=MeetingStatus.UPLOADED,
        min_speakers=source.min_speakers,
        max_speakers=source.max_speakers,
        vocabulary=source.vocabulary,
        preset_id=preset["id"],
        is_dual_track=source.is_dual_track,
    )
    db.add(copy)
    db.flush()

    dest_dir = get_meeting_path(copy.id)
    if source.is_dual_track:
        mic_src, system_src = Path(source.mic_audio_filepath), Path(source.system_audio_filepath)
        if mic_src.resolve() == system_src.resolve():
            # One stereo or multi-stream file: the pipeline splits it only when both paths
            # are the same file, so the copy keeps it as one file too.
            dest = dest_dir / f"original{mic_src.suffix}"
            _share_file(mic_src, dest)
            copy.mic_audio_filepath = copy.system_audio_filepath = str(dest)
        else:
            for attr, prefix, src in (
                ("mic_audio_filepath", "mic_source", mic_src),
                ("system_audio_filepath", "system_source", system_src),
            ):
                dest = dest_dir / f"{prefix}{src.suffix}"
                _share_file(src, dest)
                setattr(copy, attr, str(dest))
    else:
        src_path = Path(source.audio_filepath)
        dest_path = dest_dir / f"original{src_path.suffix}"
        _share_file(src_path, dest_path)
        copy.audio_filepath = str(dest_path)
    db.commit()

    _enqueue(db, copy.id, JobType.PROCESS_MEETING)
    return {**copy.to_dict(), "engine_health": health}


@router.post("/{meeting_id}/rediarize")
def rediarize_meeting(meeting_id: str, db: Session = Depends(get_db)):
    """Re-run diarization without re-transcribing."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    _reject_processing(meeting)
    if not meeting.raw_transcription:
        raise HTTPException(400, "No transcription data. Run full processing first.")
    _require_tracks(meeting, "re-diarized")
    _require_usable_diarizer()
    job = _enqueue(db, meeting.id, JobType.REDIARIZE)
    return job.to_dict()


@router.post("/{meeting_id}/reidentify")
def reidentify_meeting(meeting_id: str, db: Session = Depends(get_db)):
    """Re-run speaker identification without re-transcribing or re-diarizing."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    _reject_processing(meeting)
    if not meeting.raw_transcription or not meeting.raw_diarization:
        raise HTTPException(400, "No transcription/diarization data. Run full processing first.")
    job = _enqueue(db, meeting.id, JobType.REIDENTIFY)
    return job.to_dict()


@router.post("/{meeting_id}/reapply-vocabulary")
def reapply_vocabulary(meeting_id: str, db: Session = Depends(get_db)):
    """Re-derive Segments from stored Words and Turns using current Vocabulary."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    _reject_processing(meeting)
    if not meeting.raw_transcription or not meeting.raw_diarization:
        raise HTTPException(400, "No transcription/diarization data. Run full processing first.")
    job = _enqueue(db, meeting.id, JobType.REAPPLY_VOCABULARY)
    return job.to_dict()


@router.get("/{meeting_id}/jobs")
def list_jobs(meeting_id: str, db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(Job.meeting_id == meeting_id).order_by(Job.created_at.desc()).all()
    return [j.to_dict() for j in jobs]


@router.get("/{meeting_id}/words")
def list_words(
    meeting_id: str,
    start: float | None = None,
    end: float | None = None,
    db: Session = Depends(get_db),
):
    """The Meeting's Words as the Transcriber heard them, before Vocabulary Correction.

    ``start``/``end`` (seconds) keep the Words that overlap that range.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if start is not None and end is not None and start > end:
        raise HTTPException(400, "start must not exceed end")
    words = words_from_stored(meeting.raw_transcription)
    return [
        w.to_dict()
        for w in words
        if (end is None or w.start <= end) and (start is None or w.end >= start)
    ]
