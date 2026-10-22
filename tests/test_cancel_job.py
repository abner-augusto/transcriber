"""Cancelling a Job (plan 048): the runner loop alone stops the child and makes the transition.

These tests run the real LocalJobRunner with real spawned child processes. A body stands in
for a task: it writes the working files a task writes, says where it is, and waits to be
stopped.
"""

from datetime import datetime
import os
import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

import config
from database import Base, configure_sqlite_engine
import jobs
from jobs import running
from jobs.runners import InProcessBus, LocalJobRunner
from models import Job, Meeting, MeetingStatus, Segment, Speaker
from models.job import JobStatus, JobType

WORDS = {"words": [{"start": 0.0, "end": 1.0, "text": " antes", "confidence": 0.9}]}
TURNS = {"engine": "pyannote", "turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]}


def _folder(meeting_id: str):
    return config.get_meeting_path(meeting_id)


# --- bodies, run in the spawned child ------------------------------------------------


def _midway_body(meeting_id: str, job_id: str) -> None:
    """A task between its stages: work files on disk, then waiting."""
    with running(meeting_id, job_id) as current:
        directory = config.get_meeting_path(meeting_id)
        for name in ("audio.wav", "mic_processed.wav", "system_processed.wav", "audio.part.wav"):
            if not (directory / name).exists():  # a rerun of a processed Meeting keeps its audio.wav
                (directory / name).write_bytes(b"partial")
        current.progress(40, "Transcribing")
        (directory / "midway.flag").write_text("here")
        time.sleep(60)


def _would_run_body(meeting_id: str, job_id: str) -> None:
    """Leaves a mark if it ever starts: a cancelled PENDING Job must not."""
    with running(meeting_id, job_id):
        (config.get_meeting_path(meeting_id) / "started.flag").write_text("started")
        time.sleep(60)


def _done_then_lingering_body(meeting_id: str, job_id: str) -> None:
    """Finishes the moment the cancel is requested, then takes a while to exit.

    The request is recorded while the Job is RUNNING and the Job completes before the
    runner's loop looks at the request: the race at the natural end.
    """
    with running(meeting_id, job_id):
        while not jobs.cancel_requested(job_id):
            time.sleep(0.02)
    (config.get_meeting_path(meeting_id) / "done.flag").write_text("done")
    time.sleep(60)


def _engine_subprocess_body(meeting_id: str, job_id: str) -> None:
    """A task that started an Engine runtime (or ffmpeg): a grandchild of the runner."""
    with running(meeting_id, job_id):
        grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        directory = config.get_meeting_path(meeting_id)
        (directory / "grandchild.pid").write_text(str(grandchild.pid))
        (directory / "midway.flag").write_text("here")
        time.sleep(60)


# --- harness ---------------------------------------------------------------------------


@pytest.fixture
def runner_env(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(config.settings, "storage_path", str(storage))
    monkeypatch.setenv("STORAGE_PATH", str(storage))  # the spawned child reads its own settings
    database_url = URL.create("sqlite", database=str((tmp_path / "cancel.db").resolve())).render_as_string(
        hide_password=False
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    configure_sqlite_engine(engine)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    bus = InProcessBus()
    runner = LocalJobRunner(
        progress_bus=bus,
        session_factory=sessions,
        handler_paths={JobType.PROCESS_MEETING: f"{__name__}._midway_body"},
        poll_interval=0.01,
        minimum_timeout_seconds=120,
        duration_multiplier=0,
    )
    previous = jobs.configure(runner=runner, progress_bus=bus, session_factory=sessions)
    events = []
    original_publish = bus.publish
    bus.publish = lambda meeting_id, event: (events.append((meeting_id, event)), original_publish(meeting_id, event))[1]
    try:
        yield sessions, runner, events
    finally:
        runner.stop()
        jobs.configure(**previous)
        engine.dispose()


def _add_meeting(sessions, *, transcribed: bool, dual_track: bool = False, partial_words: bool = False) -> str:
    """A PROCESSING Meeting, as `jobs.enqueue` leaves it. `transcribed` gives it a transcript."""
    with sessions() as db:
        meeting = Meeting(
            title="Cancel", status=MeetingStatus.PROCESSING, preset_id="faster-whisper-large-v3",
            is_dual_track=dual_track,
        )
        db.add(meeting)
        db.flush()
        directory = _folder(meeting.id)
        if transcribed:
            (directory / "audio.wav").write_bytes(b"the played audio")
            meeting.audio_filepath = str(directory / "audio.wav")
            meeting.raw_transcription = WORDS
            meeting.raw_diarization = TURNS
            speaker = Speaker(meeting_id=meeting.id, label="SPEAKER_00", display_name="Ana", color="#fff")
            db.add(speaker)
            db.flush()
            db.add(Segment(
                meeting_id=meeting.id, speaker_id=speaker.id, start_time=0.0, end_time=1.0,
                text="antes (editado)", original_text="antes", order=0, is_edited=True,
            ))
        elif dual_track:
            (directory / "mic_source.wav").write_bytes(b"the upload")
            (directory / "system_source.wav").write_bytes(b"the upload")
            meeting.mic_audio_filepath = str(directory / "mic_source.wav")
            meeting.system_audio_filepath = str(directory / "system_source.wav")
        else:
            (directory / "original.mp4").write_bytes(b"the upload")
            meeting.audio_filepath = str(directory / "original.mp4")
        if partial_words:
            meeting.raw_transcription = WORDS
            meeting.raw_diarization = TURNS
        db.commit()
        return meeting.id


def _add_job(sessions, meeting_id, status=JobStatus.PENDING, created_at=None) -> str:
    with sessions() as db:
        job = Job(
            meeting_id=meeting_id, job_type=JobType.PROCESS_MEETING, status=status,
            created_at=created_at or datetime.utcnow(),
        )
        db.add(job)
        db.commit()
        return job.id


def _wait_for(predicate, what, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _wait_for_status(sessions, job_id, status, timeout=20):
    def reached():
        with sessions() as db:
            job = db.get(Job, job_id)
            return job if job and job.status == status else None

    return _wait_for(reached, f"Job {job_id} to be {status.value}", timeout)


def _wait_for_flag(meeting_id, name="midway.flag"):
    return _wait_for(lambda: (_folder(meeting_id) / name).exists(), name)


def _names(meeting_id):
    return sorted(path.name for path in _folder(meeting_id).iterdir())


def _meeting(sessions, meeting_id):
    with sessions() as db:
        meeting = db.get(Meeting, meeting_id)
        return {
            "status": meeting.status,
            "audio": meeting.audio_filepath,
            "words": meeting.raw_transcription,
            "turns": meeting.raw_diarization,
            "segments": [(s.text, s.is_edited) for s in db.query(Segment).filter_by(meeting_id=meeting_id)],
            "speakers": [s.display_name for s in db.query(Speaker).filter_by(meeting_id=meeting_id)],
        }


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# --- the intention ---------------------------------------------------------------------


def test_request_cancel_only_records_an_intention_on_an_unfinished_job(runner_env):
    sessions, _runner, _events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=False)
    pending = _add_job(sessions, meeting_id)
    finished = _add_job(sessions, meeting_id, JobStatus.COMPLETED)

    assert jobs.request_cancel(pending) is True
    assert jobs.request_cancel(finished) is False
    with sessions() as db:
        job = db.get(Job, pending)
        assert (job.status, job.cancel_requested_at is not None) == (JobStatus.PENDING, True)
        assert db.get(Job, finished).cancel_requested_at is None
        assert db.get(Meeting, meeting_id).status == MeetingStatus.PROCESSING
    first_request = _cancel_requested_at(sessions, pending)
    jobs.request_cancel(pending)
    assert _cancel_requested_at(sessions, pending) == first_request


def _cancel_requested_at(sessions, job_id):
    with sessions() as db:
        return db.get(Job, job_id).cancel_requested_at


def test_runner_cancel_writes_the_intention_and_nothing_else(runner_env):
    sessions, runner, _events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=False)
    job_id = _add_job(sessions, meeting_id)

    runner.cancel(job_id)  # the runner is not started: no loop to change anything

    with sessions() as db:
        job = db.get(Job, job_id)
        assert job.cancel_requested_at is not None
        assert job.status == JobStatus.PENDING


def test_cancel_job_changes_nothing_once_the_job_finished(runner_env):
    sessions, _runner, events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=True)
    with sessions() as db:
        db.get(Meeting, meeting_id).status = MeetingStatus.COMPLETED
        db.commit()
    for status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        job_id = _add_job(sessions, meeting_id, status)
        assert jobs.cancel_job(job_id) is False
        with sessions() as db:
            assert db.get(Job, job_id).status == status
    assert events == []


# --- PENDING ---------------------------------------------------------------------------


def test_a_pending_job_cancelled_leaves_the_queue_without_a_process(runner_env):
    sessions, runner, events = runner_env
    runner.handler_paths[JobType.PROCESS_MEETING] = f"{__name__}._would_run_body"
    meeting_id = _add_meeting(sessions, transcribed=False)
    job_id = _add_job(sessions, meeting_id)
    runner.cancel(job_id)

    runner.start()
    job = _wait_for_status(sessions, job_id, JobStatus.CANCELLED)

    assert job.completed_at is not None and job.started_at is None and job.error is None
    assert _meeting(sessions, meeting_id)["status"] == MeetingStatus.UPLOADED
    assert _names(meeting_id) == ["original.mp4"]  # no child ever ran: no started.flag
    assert (meeting_id, {"type": "cancelled"}) in events


def test_a_pending_job_of_a_completed_meeting_returns_it_to_completed_untouched(runner_env):
    sessions, runner, _events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=True)
    before = _meeting(sessions, meeting_id)
    job_id = _add_job(sessions, meeting_id)
    runner.cancel(job_id)

    runner.start()
    _wait_for_status(sessions, job_id, JobStatus.CANCELLED)

    after = _meeting(sessions, meeting_id)
    assert after.pop("status") == MeetingStatus.COMPLETED
    before.pop("status")
    assert after == before
    assert _names(meeting_id) == ["audio.wav"]


def test_a_queued_job_is_cancelled_while_another_runs(runner_env):
    sessions, runner, _events = runner_env
    running_meeting = _add_meeting(sessions, transcribed=False)
    queued_meeting = _add_meeting(sessions, transcribed=False)
    running_id = _add_job(sessions, running_meeting, created_at=datetime(2026, 1, 1))
    queued_id = _add_job(sessions, queued_meeting, created_at=datetime(2026, 1, 2))
    runner.start()
    _wait_for_flag(running_meeting)

    runner.cancel(queued_id)

    _wait_for_status(sessions, queued_id, JobStatus.CANCELLED)
    with sessions() as db:
        assert db.get(Job, running_id).status == JobStatus.RUNNING
    assert _meeting(sessions, queued_meeting)["status"] == MeetingStatus.UPLOADED


# --- RUNNING ---------------------------------------------------------------------------


def test_cancelling_a_first_transcription_returns_the_meeting_to_uploaded(runner_env):
    sessions, runner, events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=False, partial_words=True)
    job_id = _add_job(sessions, meeting_id)
    runner.start()
    _wait_for_flag(meeting_id)

    runner.cancel(job_id)
    job = _wait_for_status(sessions, job_id, JobStatus.CANCELLED)

    assert job.completed_at is not None and job.error is None
    meeting = _meeting(sessions, meeting_id)
    assert meeting["status"] == MeetingStatus.UPLOADED
    assert (meeting["words"], meeting["turns"], meeting["segments"], meeting["speakers"]) == (None, None, [], [])
    # The upload is still there to start again; the Job's working files are gone.
    assert meeting["audio"].endswith("original.mp4")
    assert _names(meeting_id) == ["midway.flag", "original.mp4"]
    assert (meeting_id, {"type": "cancelled"}) in events


def test_cancelling_a_first_transcription_of_a_dual_track_meeting_keeps_its_sources(runner_env):
    sessions, runner, _events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=False, dual_track=True)
    job_id = _add_job(sessions, meeting_id)
    runner.start()
    _wait_for_flag(meeting_id)

    runner.cancel(job_id)
    _wait_for_status(sessions, job_id, JobStatus.CANCELLED)

    assert _meeting(sessions, meeting_id)["status"] == MeetingStatus.UPLOADED
    assert _names(meeting_id) == ["mic_source.wav", "midway.flag", "system_source.wav"]


def test_cancelling_a_reprocessing_returns_the_meeting_to_completed_with_its_transcript(runner_env):
    sessions, runner, _events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=True)
    before = _meeting(sessions, meeting_id)
    job_id = _add_job(sessions, meeting_id)
    runner.start()
    _wait_for_flag(meeting_id)

    runner.cancel(job_id)
    _wait_for_status(sessions, job_id, JobStatus.CANCELLED)

    after = _meeting(sessions, meeting_id)
    assert after.pop("status") == MeetingStatus.COMPLETED
    before.pop("status")
    assert after == before  # Words, Turns, the edited Segment, the named Speaker, the audio path
    # The audio the page plays is the one the Meeting had; the Job's partial files are gone.
    assert _names(meeting_id) == ["audio.wav", "midway.flag"]
    assert (_folder(meeting_id) / "audio.wav").read_bytes() == b"the played audio"


def test_the_runner_goes_on_with_the_next_job_after_a_cancel(runner_env):
    sessions, runner, _events = runner_env
    first_meeting = _add_meeting(sessions, transcribed=False)
    second_meeting = _add_meeting(sessions, transcribed=False)
    first = _add_job(sessions, first_meeting, created_at=datetime(2026, 1, 1))
    second = _add_job(sessions, second_meeting, created_at=datetime(2026, 1, 2))
    runner.start()
    _wait_for_flag(first_meeting)

    runner.cancel(first)

    _wait_for_status(sessions, first, JobStatus.CANCELLED)
    _wait_for_status(sessions, second, JobStatus.RUNNING)
    _wait_for_flag(second_meeting)


def test_the_engine_runtime_the_child_started_is_stopped_with_it(runner_env):
    sessions, runner, _events = runner_env
    runner.handler_paths[JobType.PROCESS_MEETING] = f"{__name__}._engine_subprocess_body"
    meeting_id = _add_meeting(sessions, transcribed=False)
    job_id = _add_job(sessions, meeting_id)
    runner.start()
    _wait_for_flag(meeting_id)
    grandchild = int((_folder(meeting_id) / "grandchild.pid").read_text())
    assert _alive(grandchild)

    runner.cancel(job_id)
    _wait_for_status(sessions, job_id, JobStatus.CANCELLED)

    _wait_for(lambda: not _alive(grandchild), "the grandchild process to be gone", timeout=10)


# --- the race --------------------------------------------------------------------------


def test_a_cancel_that_loses_the_race_with_the_natural_end_leaves_the_job_completed(runner_env):
    sessions, runner, events = runner_env
    runner.handler_paths[JobType.PROCESS_MEETING] = f"{__name__}._done_then_lingering_body"
    meeting_id = _add_meeting(sessions, transcribed=True)
    job_id = _add_job(sessions, meeting_id)
    # The loop reads the request as still pending (it read the Job while it was RUNNING),
    # but only once the child has completed: the commit lands between the read and the stop.
    looks = threading.Event()
    runner._cancel_requested = lambda job: looks.is_set()
    runner.start()
    _wait_for_status(sessions, job_id, JobStatus.RUNNING)

    runner.cancel(job_id)  # recorded: the Job is still RUNNING
    _wait_for_flag(meeting_id, "done.flag")  # the child completed; it has not exited yet
    assert runner._active_process is not None
    looks.set()
    _wait_for(lambda: runner._active_process is None, "the runner to let go of the child")

    with sessions() as db:
        job = db.get(Job, job_id)
        assert job.status == JobStatus.COMPLETED
        assert db.get(Meeting, meeting_id).status == MeetingStatus.COMPLETED
    assert (meeting_id, {"type": "cancelled"}) not in events
    assert _meeting(sessions, meeting_id)["segments"] == [("antes (editado)", True)]


def test_cancelling_and_failing_together_leave_one_end_state(runner_env):
    """The shutdown path and a cancel both stop the child; whichever transition ran first holds."""
    sessions, runner, _events = runner_env
    meeting_id = _add_meeting(sessions, transcribed=False)
    job_id = _add_job(sessions, meeting_id)
    runner.start()
    _wait_for_flag(meeting_id)

    runner.cancel(job_id)
    _wait_for_status(sessions, job_id, JobStatus.CANCELLED)
    assert jobs.fail(job_id, "late failure") is False  # a CANCELLED Job is finished

    with sessions() as db:
        assert db.get(Job, job_id).status == JobStatus.CANCELLED
        assert db.get(Meeting, meeting_id).status == MeetingStatus.UPLOADED
