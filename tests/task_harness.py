"""Runs the real Celery task bodies against SQLite, fake Engines, and fake VAD.

Everything the tasks reach for — audio extraction, VAD, the Engine factories, the
progress publisher, the Meeting storage directory — is replaced here, so a test only
states the Meeting and the Engine outputs it cares about.
"""

from dataclasses import dataclass, field

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
import jobs
from jobs.runners import InProcessBus
from engines import DiarizationResult, Transcription, Turn, Word
from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType
from preferences import DiarizationPrefs, VocabularyCorrectionPrefs, WhisperDtwPrefs
from run_config import RunConfig
from services.audio_service import DUAL_MIC_OUTPUT, DUAL_SYSTEM_OUTPUT

from .fakes import FakeDiarizer, FakeTranscriber


class NativeTranscriber(FakeTranscriber):
    """A Transcriber that also produces its own Turns, the way VibeVoice does."""

    def __init__(self, words: list[Word], native: DiarizationResult):
        super().__init__(words)
        self.native = native

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> Transcription:
        self.calls.append((audio_path, vocabulary))
        self.lifecycle.append("transcribe")
        return Transcription(words=list(self.words), native=self.native)


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

TEST_RUN_CONFIG = RunConfig(
    preset={"id": "harness", "name": "Harness", "engine": "test", "model_path": "test-model"},
    whisper_dtw=WhisperDtwPrefs(),
    diarization=DiarizationPrefs(),
    speaker_switch_penalty=0.5,
    speaker_profiles_enabled=False,
    vocabulary_correction=VocabularyCorrectionPrefs(),
)


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
    preset = (
        {"id": "vibevoice-7b", "name": "VibeVoice", "engine": "vibevoice", "model_path": "test-model"}
        if isinstance(transcriber, NativeTranscriber)
        else {
            "id": "whisper-large-v3-turbo", "name": "Whisper", "engine": "whisper.cpp",
            "model_path": "test-model",
        }
    )
    run_config = TEST_RUN_CONFIG.model_copy(update={"preset": preset})

    def compute_vad_segments(self, path):
        harness.vad_calls.append(str(path))
        for name, regions in VAD_BY_FILE.items():
            if str(path).endswith(name):
                return list(regions)
        return list(DEFAULT_VAD)

    jobs.configure(session_factory=session_factory, progress_bus=InProcessBus())
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: run_config)
    monkeypatch.setattr("tasks.process_meeting.make_transcriber", lambda run_config: transcriber)
    monkeypatch.setattr("tasks.process_meeting.make_diarizer", lambda run_config, **kwargs: diarizer)
    monkeypatch.setattr("tasks.reprocess_task.make_diarizer", lambda run_config, **kwargs: diarizer)
    monkeypatch.setattr("tasks.reprocess_task.hf_token", lambda: "")
    monkeypatch.setattr("preferences.hf_token", lambda: "")
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
    engine="vibevoice",
)
