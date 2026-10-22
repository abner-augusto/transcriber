"""A Job saves its results in one transaction, so stopping it leaves the Meeting whole (plan 048).

The runner stops a cancelled Job by killing its child process, which runs no cleanup. A
kill is simulated here with a BaseException: ``running()`` catches only Exception, so the
Job is left RUNNING and nothing after the raising stage runs, exactly like a dead process.
"""

import pytest

from engines import DiarizationResult, Turn, Word
from models import Job, Meeting, MeetingStatus, Segment
from models.job import JobStatus, JobType
from tasks.process_meeting import process_meeting_task
from tasks.reprocess_task import rediarize_task

from . import task_harness as h
from .fakes import FakeDiarizer, FakeTranscriber

OLD_WORDS = [
    Word(start=0.1, end=0.6, text=" antes"),
    Word(start=1.2, end=1.8, text=" do"),
    Word(start=3.2, end=3.8, text=" corte"),
]
NEW_WORDS = [
    Word(start=0.1, end=0.6, text=" depois"),
    Word(start=1.2, end=1.8, text=" do"),
    Word(start=3.2, end=3.8, text=" cancelamento"),
]
OLD_TURNS = DiarizationResult(turns=[Turn(0.0, 4.0, "SPEAKER_00")], exclusive_turns=[Turn(0.0, 4.0, "SPEAKER_00")])
NEW_TURNS = DiarizationResult(
    turns=[Turn(0.0, 2.0, "SPEAKER_05"), Turn(2.0, 4.0, "SPEAKER_06")],
    exclusive_turns=[Turn(0.0, 2.0, "SPEAKER_05"), Turn(2.0, 4.0, "SPEAKER_06")],
)


class Killed(BaseException):
    """The child process was killed here."""


def _completed(monkeypatch, tmp_path, **columns):
    harness = h.install(
        monkeypatch, tmp_path, transcriber=FakeTranscriber(OLD_WORDS), diarization=OLD_TURNS
    )
    meeting_id = harness.meeting(**columns)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="uploaded")
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    return harness, meeting_id


def _use_new_results(monkeypatch):
    monkeypatch.setattr("tasks.process_meeting.make_transcriber", lambda run_config: FakeTranscriber(NEW_WORDS))
    monkeypatch.setattr(
        "tasks.process_meeting.make_diarizer", lambda run_config, **kwargs: FakeDiarizer(NEW_TURNS)
    )


def _stored(harness, meeting_id):
    """Everything a Reprocessing could change, read back with a fresh session."""
    with harness.session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        return {
            "audio": meeting.audio_filepath,
            "duration": meeting.duration,
            "words": meeting.raw_transcription,
            "turns": meeting.raw_diarization,
            "segments": [
                (s.start_time, s.end_time, s.text, s.speaker.label)
                for s in db.query(Segment).filter(Segment.meeting_id == meeting_id).order_by(Segment.order)
            ],
        }


def _kill_at(monkeypatch, target: str):
    def kill(*args, **kwargs):
        raise Killed

    monkeypatch.setattr(target, kill)


def _kill_after(monkeypatch, module, name: str):
    """Let ``module.name`` run, then die: the kill lands right behind it."""
    original = getattr(module, name)

    def run_then_die(*args, **kwargs):
        original(*args, **kwargs)
        raise Killed

    monkeypatch.setattr(module, name, run_then_die)


# --- a Reprocessing of a COMPLETED Meeting saves nothing until its one final transaction ---


@pytest.mark.parametrize(
    "stage",
    [
        "tests.fakes.FakeDiarizer.diarize",
        "services.speaker_id_service.SpeakerIdService.name_speakers",
        "meeting_store._write_segments",
    ],
)
def test_full_reprocess_killed_midway_leaves_the_previous_transcript_whole(monkeypatch, tmp_path, stage):
    harness, meeting_id = _completed(monkeypatch, tmp_path)
    before = _stored(harness, meeting_id)
    assert before["segments"], "the first run must have produced a transcript to protect"
    _use_new_results(monkeypatch)
    _kill_at(monkeypatch, stage)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="completed")

    with pytest.raises(Killed):
        process_meeting_task(meeting_id, job_id)

    assert _stored(harness, meeting_id) == before


def test_full_reprocess_killed_right_after_the_rebuild_but_before_the_final_commit_changes_nothing(
    monkeypatch, tmp_path
):
    """The window between the Segments being written and the Job being COMPLETED."""
    import meeting_store

    harness, meeting_id = _completed(monkeypatch, tmp_path)
    before = _stored(harness, meeting_id)
    _use_new_results(monkeypatch)
    _kill_after(monkeypatch, meeting_store, "_finish_rebuild")
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="completed")

    with pytest.raises(Killed):
        process_meeting_task(meeting_id, job_id)

    assert _stored(harness, meeting_id) == before
    with harness.session_factory() as db:
        assert db.get(Job, job_id).status == JobStatus.RUNNING  # still unfinished: a cancel may take it


def test_full_reprocess_killed_after_the_final_commit_is_complete_with_the_new_results(monkeypatch, tmp_path):
    """Too late to cancel: the one transaction already holds the results and the Job's COMPLETED."""
    harness, meeting_id = _completed(monkeypatch, tmp_path)
    _use_new_results(monkeypatch)
    _kill_at(monkeypatch, "tasks.process_meeting.delete_raw_audio")  # runs after the commit
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="completed")

    with pytest.raises(Killed):
        process_meeting_task(meeting_id, job_id)

    after = _stored(harness, meeting_id)
    assert [segment[2] for segment in after["segments"]] == ["depois do", "cancelamento"]
    with harness.session_factory() as db:
        assert db.get(Job, job_id).status == JobStatus.COMPLETED
        assert db.get(Meeting, meeting_id).status == MeetingStatus.COMPLETED


def test_full_reprocess_that_finishes_replaces_everything_together(monkeypatch, tmp_path):
    harness, meeting_id = _completed(monkeypatch, tmp_path)
    _use_new_results(monkeypatch)

    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="completed")
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"

    after = _stored(harness, meeting_id)
    assert [segment[2] for segment in after["segments"]] == ["depois do", "cancelamento"]
    assert [word["text"] for word in after["words"]["words"]] == [" depois", " do", " cancelamento"]
    assert {turn["speaker"] for turn in after["turns"]["turns"]} == {"SPEAKER_05", "SPEAKER_06"}


@pytest.mark.parametrize(
    "stage",
    [
        "services.speaker_id_service.SpeakerIdService.name_speakers",
        "meeting_store._write_segments",
    ],
)
def test_rediarize_killed_midway_keeps_the_previous_turns_and_segments(monkeypatch, tmp_path, stage):
    harness, meeting_id = _completed(monkeypatch, tmp_path)
    before = _stored(harness, meeting_id)
    monkeypatch.setattr("tasks.reprocess_task.make_diarizer", lambda run_config, **kwargs: FakeDiarizer(NEW_TURNS))
    _kill_at(monkeypatch, stage)
    job_id = harness.job(meeting_id, JobType.REDIARIZE, previous="completed")

    with pytest.raises(Killed):
        rediarize_task(meeting_id, job_id)

    assert _stored(harness, meeting_id) == before


# --- a first transcription still saves each stage, so a late failure can be reprocessed ---


def test_a_first_transcription_that_fails_late_keeps_its_audio_words_and_turns(monkeypatch, tmp_path):
    harness = h.install(monkeypatch, tmp_path, transcriber=FakeTranscriber(OLD_WORDS), diarization=OLD_TURNS)
    meeting_id = harness.meeting()
    def disk_full(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("meeting_store._write_segments", disk_full)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="uploaded")

    with pytest.raises(RuntimeError, match="disk full"):
        process_meeting_task(meeting_id, job_id)

    stored = _stored(harness, meeting_id)
    assert [word["text"] for word in stored["words"]["words"]] == [" antes", " do", " corte"]
    assert stored["turns"]["turns"] and stored["audio"] and stored["duration"] == 4.0
    assert stored["segments"] == []
    with harness.session_factory() as db:
        assert db.get(Meeting, meeting_id).status == MeetingStatus.FAILED
    # The Words and Turns are what Re-diarize, Re-identify and Reapply vocabulary run from.

def test_a_first_transcription_killed_midway_leaves_the_stages_it_finished(monkeypatch, tmp_path):
    harness = h.install(monkeypatch, tmp_path, transcriber=FakeTranscriber(OLD_WORDS), diarization=OLD_TURNS)
    meeting_id = harness.meeting()
    _kill_at(monkeypatch, "services.speaker_id_service.SpeakerIdService.name_speakers")
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="uploaded")

    with pytest.raises(Killed):
        process_meeting_task(meeting_id, job_id)

    stored = _stored(harness, meeting_id)
    assert stored["words"] and stored["turns"] and stored["segments"] == []


# --- the dual-track mix of a Reprocessing is installed only once it is committed ---


def _dual_track(monkeypatch, tmp_path):
    """A COMPLETED dual-track Meeting ready for a Full reprocess, and what AudioService was asked."""
    import services.audio_service as audio_service

    harness = h.install(monkeypatch, tmp_path, transcriber=FakeTranscriber(OLD_WORDS), diarization=OLD_TURNS)
    meeting_id = harness.meeting(dual_track=True)
    asked = {"defer_mix": [], "installed": []}

    def extract(self, mic, system, mid, layout=None, defer_mix=False):
        asked["defer_mix"].append(defer_mix)
        harness.write_dual_tracks(mid)
        return str(harness.storage / mid / ("audio.part.wav" if defer_mix else "audio.wav"))

    def install(mid):
        with harness.session_factory() as db:  # the mix moves only after the commit
            asked["installed"].append(db.query(Job).filter_by(meeting_id=mid).all()[-1].status)

    monkeypatch.setattr(audio_service.AudioService, "extract_dual_audio", extract)
    monkeypatch.setattr(audio_service.AudioService, "install_mix", staticmethod(install))
    return harness, meeting_id, asked


def test_a_dual_track_reprocessing_reads_the_part_and_installs_it_after_the_commit(monkeypatch, tmp_path):
    harness, meeting_id, asked = _dual_track(monkeypatch, tmp_path)
    first = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="uploaded")
    assert process_meeting_task(meeting_id, first)["status"] == "completed"
    with harness.session_factory() as db:  # the originals, where a rerun reads them
        meeting = db.get(Meeting, meeting_id)
        meeting.mic_audio_filepath = str(harness.storage / "mic.wav")
        meeting.system_audio_filepath = str(harness.storage / "system.wav")
        db.commit()
    audio_before = _stored(harness, meeting_id)["audio"]

    second = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="completed")
    assert process_meeting_task(meeting_id, second)["status"] == "completed"

    assert asked["defer_mix"] == [False, True]  # a first run writes audio.wav; a rerun defers
    assert asked["installed"] == [JobStatus.COMPLETED]  # only the rerun, and only once committed
    assert _stored(harness, meeting_id)["audio"] == audio_before  # audio.wav, never the .part


def test_a_dual_track_reprocessing_killed_midway_never_installs_the_mix(monkeypatch, tmp_path):
    harness, meeting_id, asked = _dual_track(monkeypatch, tmp_path)
    first = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="uploaded")
    process_meeting_task(meeting_id, first)
    with harness.session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        meeting.mic_audio_filepath = str(harness.storage / "mic.wav")
        meeting.system_audio_filepath = str(harness.storage / "system.wav")
        db.commit()
    _kill_at(monkeypatch, "services.speaker_id_service.SpeakerIdService.name_speakers")

    second = harness.job(meeting_id, JobType.PROCESS_MEETING, previous="completed")
    with pytest.raises(Killed):
        process_meeting_task(meeting_id, second)

    assert asked["installed"] == []
