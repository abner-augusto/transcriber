"""Speaker names and Segment reassignments survive Reprocessing (plan 028)."""

from fastapi.testclient import TestClient

from database import get_db
from engines import DiarizationResult, Turn, Word
from main import app
from models import Segment, Speaker
from models.job import JobType
from tasks.process_meeting import process_meeting_task
from tasks.reprocess_task import reapply_vocabulary_task, reidentify_task, rediarize_task

from . import task_harness as h
from .fakes import FakeTranscriber

# Three Segments: A speaks (0.1-0.8), B answers (0.95-1.2), A speaks again (2.6-3.2).
# The last two start more than EDIT_TIME_TOLERANCE apart, so a reassignment of one
# never matches the other. The Meeting is 4s long: the harness clips Turns to it.
WORDS = [
    Word(start=0.1, end=0.3, text=" um"),
    Word(start=0.35, end=0.55, text=" dois"),
    Word(start=0.6, end=0.8, text=" tres"),
    Word(start=0.95, end=1.2, text=" quatro"),
    Word(start=2.6, end=3.2, text=" cinco"),
]


def _result(first: str, second: str) -> DiarizationResult:
    turns = [
        Turn(start=0.0, end=0.9, speaker=first),
        Turn(start=0.9, end=2.0, speaker=second),
        Turn(start=2.0, end=4.0, speaker=first),
    ]
    return DiarizationResult(turns=turns, exclusive_turns=list(turns))


def _processed(monkeypatch, tmp_path):
    harness = h.install(
        monkeypatch, tmp_path, transcriber=FakeTranscriber(WORDS),
        diarization=_result("SPEAKER_00", "SPEAKER_01"),
    )
    meeting_id = harness.meeting()
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    return harness, meeting_id


def _run(harness, meeting_id, task, job_type):
    assert task(meeting_id, harness.job(meeting_id, job_type))["status"] == "completed"


def _speaker(harness, meeting_id, label) -> Speaker | None:
    return next((s for s in harness.load(meeting_id).speakers if s.label == label), None)


def _name(harness, meeting_id, label, name):
    with harness.session_factory() as db:
        speaker = db.query(Speaker).filter_by(meeting_id=meeting_id, label=label).one()
        speaker.display_name = name
        speaker.identified_by = "manual"
        db.commit()


def _owner_labels(harness, meeting_id) -> list[str | None]:
    segments = sorted(harness.load(meeting_id).segments, key=lambda s: s.order)
    return [s.speaker.label if s.speaker else None for s in segments]


def _reassign(harness, meeting_id, order, label):
    """Move the Segment at `order` to the Speaker `label`, the way the route does."""
    with harness.session_factory() as db:
        target = db.query(Speaker).filter_by(meeting_id=meeting_id, label=label).one()
        segment = db.query(Segment).filter_by(meeting_id=meeting_id, order=order).one()
        segment.speaker_id = target.id
        segment.speaker_edited = True
        db.commit()


def test_reidentify_keeps_a_manual_name(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _name(harness, meeting_id, "SPEAKER_00", "Maria")

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    maria = _speaker(harness, meeting_id, "SPEAKER_00")
    assert (maria.display_name, maria.identified_by) == ("Maria", "manual")
    assert _speaker(harness, meeting_id, "SPEAKER_01").display_name == "Participant 2"


def test_rediarize_moves_a_manual_name_to_the_overlapping_label(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _name(harness, meeting_id, "SPEAKER_00", "Maria")
    harness.diarizer.result = _result("SPEAKER_01", "SPEAKER_00")

    _run(harness, meeting_id, rediarize_task, JobType.REDIARIZE)

    maria = _speaker(harness, meeting_id, "SPEAKER_01")
    assert (maria.display_name, maria.identified_by) == ("Maria", "manual")
    assert _speaker(harness, meeting_id, "SPEAKER_00").display_name == "Participant 1"


def test_rediarize_drops_a_name_without_enough_overlap(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _name(harness, meeting_id, "SPEAKER_00", "Maria")
    # Maria's old Segments cover 0.1-0.8 and 2.6-3.2 (1.3s). The new Turns split
    # that time over four labels, none holding half of it.
    turns = [
        Turn(start=0.0, end=0.32, speaker="SPEAKER_05"),
        Turn(start=0.32, end=0.58, speaker="SPEAKER_06"),
        Turn(start=0.58, end=0.9, speaker="SPEAKER_08"),
        Turn(start=0.9, end=2.0, speaker="SPEAKER_01"),
        Turn(start=2.0, end=4.0, speaker="SPEAKER_07"),
    ]
    harness.diarizer.result = DiarizationResult(turns=turns, exclusive_turns=list(turns))

    _run(harness, meeting_id, rediarize_task, JobType.REDIARIZE)

    assert _owner_labels(harness, meeting_id) == [
        "SPEAKER_05", "SPEAKER_06", "SPEAKER_08", "SPEAKER_01", "SPEAKER_07"
    ]
    names = {s.label: (s.display_name, s.identified_by) for s in harness.load(meeting_id).speakers}
    assert names
    assert all(name != "Maria" and by != "manual" for name, by in names.values())


def test_reidentify_reapplies_a_segment_reassignment(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    _reassign(harness, meeting_id, 2, "SPEAKER_01")

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"]
    moved = [s for s in harness.load(meeting_id).segments if s.speaker_edited]
    assert [s.order for s in moved] == [2]


def test_reapply_vocabulary_reapplies_a_segment_reassignment(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _reassign(harness, meeting_id, 2, "SPEAKER_01")

    _run(harness, meeting_id, reapply_vocabulary_task, JobType.REAPPLY_VOCABULARY)

    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"]


def test_rediarize_drops_reassignments(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _reassign(harness, meeting_id, 2, "SPEAKER_01")

    _run(harness, meeting_id, rediarize_task, JobType.REDIARIZE)

    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    assert not any(s.speaker_edited for s in harness.load(meeting_id).segments)


def test_a_voice_profile_match_does_not_override_a_manual_name(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _name(harness, meeting_id, "SPEAKER_01", "Maria")
    monkeypatch.setattr(
        "services.speaker_id_service.SpeakerIdService.name_speakers",
        lambda self, db, labels, *args, **kwargs: {
            label: {"name": "Matched", "identified_by": "voice_profile", "confidence": 0.9}
            for label in labels
        },
    )

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    maria = _speaker(harness, meeting_id, "SPEAKER_01")
    assert (maria.display_name, maria.identified_by) == ("Maria", "manual")
    assert _speaker(harness, meeting_id, "SPEAKER_00").display_name == "Matched"


def test_manual_speaker_survives_reidentify(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    with harness.session_factory() as db:
        db.add(Speaker(
            meeting_id=meeting_id, label="MANUAL_1", display_name="Joao", color="#123456",
            identified_by="manual", segment_count=0, total_speaking_time=0.0,
        ))
        db.commit()
    _reassign(harness, meeting_id, 2, "MANUAL_1")

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    joao = _speaker(harness, meeting_id, "MANUAL_1")
    assert (joao.display_name, joao.color, joao.identified_by) == ("Joao", "#123456", "manual")
    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00", "SPEAKER_01", "MANUAL_1"]
    assert joao.segment_count == 1


def test_a_diarized_speaker_left_without_segments_is_deleted(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _reassign(harness, meeting_id, 1, "SPEAKER_00")

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00"] * 3
    assert _speaker(harness, meeting_id, "SPEAKER_01") is None


def test_an_empty_manual_speaker_is_kept(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    with harness.session_factory() as db:
        db.add(Speaker(
            meeting_id=meeting_id, label="MANUAL_1", display_name="Joao", color="#123456",
            identified_by="manual", segment_count=0, total_speaking_time=0.0,
        ))
        db.commit()

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    assert _speaker(harness, meeting_id, "MANUAL_1") is not None


def _client(harness):
    def override_get_db():
        db = harness.session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_a_reassignment_made_through_the_route_survives_reidentify(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    try:
        client = _client(harness)
        meeting = harness.load(meeting_id)
        last = next(s for s in meeting.segments if s.order == 2)
        second = next(s for s in meeting.speakers if s.label == "SPEAKER_01")
        response = client.put(f"/api/segments/{last.id}/speaker", json={"speaker_id": second.id})
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"]


def test_a_merge_survives_reidentify(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    try:
        client = _client(harness)
        speakers = {s.label: s for s in harness.load(meeting_id).speakers}
        response = client.post("/api/speakers/merge", json={
            "source_id": speakers["SPEAKER_01"].id, "target_id": speakers["SPEAKER_00"].id,
        })
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00"] * 3
    assert _speaker(harness, meeting_id, "SPEAKER_01") is None


def test_stats_are_recounted_after_overrides(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path)
    _reassign(harness, meeting_id, 2, "SPEAKER_01")

    _run(harness, meeting_id, reidentify_task, JobType.REIDENTIFY)

    meeting = harness.load(meeting_id)
    for speaker in meeting.speakers:
        owned = [s for s in meeting.segments if s.speaker_id == speaker.id]
        assert speaker.segment_count == len(owned)
        assert speaker.total_speaking_time == sum(s.end_time - s.start_time for s in owned)
    assert {s.label: s.segment_count for s in meeting.speakers} == {"SPEAKER_00": 1, "SPEAKER_01": 2}
    assert _owner_labels(harness, meeting_id) == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"]
