"""SpeakerIdService: sample selection for voice profiles, and Participant naming."""

from engines import Turn
from services.speaker_id_service import SpeakerIdService


def test_speaker_id_best_turns_selection():
    service = SpeakerIdService()
    turns = [
        Turn(start=0.0, end=1.5, speaker="SPEAKER_00"),   # 1.5s
        Turn(start=2.0, end=7.0, speaker="SPEAKER_00"),   # 5.0s
        Turn(start=8.0, end=14.0, speaker="SPEAKER_00"),  # 6.0s
        Turn(start=15.0, end=25.0, speaker="SPEAKER_00"), # 10.0s
        Turn(start=26.0, end=30.0, speaker="SPEAKER_01"), # Other speaker
    ]

    # Max 15s sample should select the longest turns first: 10s + 6s -> total >= 15s
    best = service._best_turns_for_speaker(turns, "SPEAKER_00", max_total_seconds=15.0)

    assert len(best) == 2
    assert best[0].start == 15.0  # 10s turn
    assert best[1].start == 8.0   # 6s turn


def test_speaker_id_best_turns_fallback_to_short_turns():
    service = SpeakerIdService()
    # Turns shorter than 2.0s but >= 1.0s
    turns = [
        Turn(start=0.0, end=1.2, speaker="SPEAKER_00"),
        Turn(start=2.0, end=3.5, speaker="SPEAKER_00"),
    ]

    best = service._best_turns_for_speaker(turns, "SPEAKER_00")
    assert len(best) >= 1
    assert best[0].start == 2.0


def test_speakers_are_named_participant_n_in_label_order(monkeypatch, tmp_path):
    from models import JobType
    from tasks.process_meeting import process_meeting_task

    from . import task_harness as h
    from .fakes import FakeTranscriber

    harness = h.install(monkeypatch, tmp_path, transcriber=FakeTranscriber(h.WORDS), diarization=h.PYANNOTE)
    meeting_id = harness.meeting()
    assert process_meeting_task(meeting_id, harness.job(meeting_id, JobType.PROCESS_MEETING))["status"] == "completed"

    speakers = sorted((s.label, s.display_name) for s in harness.load(meeting_id).speakers)
    assert speakers == [("SPEAKER_00", "Participant 1"), ("SPEAKER_01", "Participant 2")]
