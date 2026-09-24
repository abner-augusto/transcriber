"""Runs the real Celery task bodies against SQLite, fake Engines, and fake VAD.

Everything the tasks reach for — audio extraction, VAD, the Engine factories, the
progress publisher, the Meeting storage directory — is replaced here, so a test only
states the Meeting and the Engine outputs it cares about.
"""

from dataclasses import dataclass, field

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from engines import DiarizationResult, Turn, Word
from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType
from services.audio_service import DUAL_MIC_OUTPUT, DUAL_SYSTEM_OUTPUT

from .fakes import FakeDiarizer, FakeTranscriber


class NativeTranscriber(FakeTranscriber):
    """A Transcriber that also produces its own Turns, the way VibeVoice does."""

    has_native_diarization = True

    def __init__(self, words: list[Word], native: DiarizationResult):
        super().__init__(words)
        self.native = native

    def get_native_diarization(self) -> DiarizationResult:
        return self.native


@dataclass
class TaskHarness:
    session_factory: sessionmaker
    storage: object
    diarizer: FakeDiarizer
    vad_calls: list[str] = field(default_factory=list)

    def meeting(self, *, dual_track: bool = False, **columns) -> str:
        with self.session_factory() as db:
            meeting = Meeting(
                title="Harness",
                status=MeetingStatus.UPLOADED,
                audio_filepath=str(self.storage / "source.wav"),
                is_dual_track=dual_track,
                **columns,
            )
            if dual_track:
                meeting.mic_audio_filepath = str(self.storage / "mic.wav")
                meeting.system_audio_filepath = str(self.storage / "system.wav")
            db.add(meeting)
            db.commit()
            return meeting.id

    def track_dir(self, meeting_id: str):
        return self.storage / meeting_id

    def write_dual_tracks(self, meeting_id: str) -> None:
        directory = self.track_dir(meeting_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / DUAL_MIC_OUTPUT).write_bytes(b"")
        (directory / DUAL_SYSTEM_OUTPUT).write_bytes(b"")

    def job(self, meeting_id: str, job_type: JobType) -> str:
        with self.session_factory() as db:
            job = Job(meeting_id=meeting_id, job_type=job_type, status=JobStatus.PENDING)
            db.add(job)
            db.commit()
            return job.id

    def load(self, meeting_id: str) -> Meeting:
        db = self.session_factory()
        meeting = db.get(Meeting, meeting_id)
        # Touch the relationships while the session is open.
        list(meeting.speakers)
        list(meeting.segments)
        return meeting

    def job_row(self, job_id: str) -> Job:
        with self.session_factory() as db:
            return db.get(Job, job_id)


# Speech regions the fake VAD reports, keyed by the file name it is asked about.
VAD_BY_FILE = {
    DUAL_MIC_OUTPUT: [(0.0, 1.0)],
    DUAL_SYSTEM_OUTPUT: [(0.5, 3.0)],
}
DEFAULT_VAD = [(0.0, 4.0)]


def install(monkeypatch, tmp_path, *, transcriber, diarization: DiarizationResult) -> TaskHarness:
    """Patch the task modules and return a harness bound to a fresh SQLite database."""
    import config

    engine = create_engine(f"sqlite:///{tmp_path / 'tasks.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(config.settings, "storage_path", str(storage))

    diarizer = FakeDiarizer(diarization)
    harness = TaskHarness(session_factory=session_factory, storage=storage, diarizer=diarizer)

    def compute_vad_segments(self, path):
        harness.vad_calls.append(str(path))
        for name, regions in VAD_BY_FILE.items():
            if str(path).endswith(name):
                return list(regions)
        return list(DEFAULT_VAD)

    monkeypatch.setattr("tasks.shared.SessionLocal", session_factory)
    monkeypatch.setattr("tasks.shared.publish_event", lambda meeting_id, data: None)
    monkeypatch.setattr("tasks.process_meeting.make_transcriber", lambda preset: transcriber)
    monkeypatch.setattr("tasks.process_meeting.make_diarizer", lambda: diarizer)
    monkeypatch.setattr("tasks.reprocess_task.make_diarizer", lambda: diarizer)
    monkeypatch.setattr("services.audio_service.AudioService.extract_audio", lambda self, fp, mid: fp)
    monkeypatch.setattr(
        "services.audio_service.AudioService.extract_dual_audio",
        lambda self, mic, system, mid: str(storage / mid / "mixed.wav"),
    )
    monkeypatch.setattr("services.audio_service.AudioService.get_duration", lambda self, fp: 4.0)
    monkeypatch.setattr("services.vad_service.VadService.compute_vad_segments", compute_vad_segments)
    return harness


WORDS = [
    Word(start=0.1, end=0.6, text=" olá"),
    Word(start=1.2, end=1.8, text=" pessoal"),
    Word(start=3.2, end=3.8, text=" tudo"),
]

PYANNOTE = DiarizationResult(
    turns=[
        Turn(start=0.0, end=2.0, speaker="SPEAKER_00"),
        Turn(start=1.5, end=6.0, speaker="SPEAKER_01"),
    ],
    exclusive_turns=[
        Turn(start=0.0, end=1.5, speaker="SPEAKER_00"),
        Turn(start=1.5, end=6.0, speaker="SPEAKER_01"),
    ],
)

NATIVE = DiarizationResult(
    turns=[
        Turn(start=0.0, end=1.0, speaker="SPEAKER_0"),
        Turn(start=1.0, end=5.0, speaker="SPEAKER_1"),
    ],
)
