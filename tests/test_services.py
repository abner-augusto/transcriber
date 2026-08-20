"""Unit tests for services: AudioService and SpeakerIdService."""

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


def test_speaker_id_participant_names():
    service = SpeakerIdService()
    names = service._participant_names(["SPEAKER_01", "SPEAKER_00"])
    assert names["SPEAKER_00"]["name"] == "Participant 1"
    assert names["SPEAKER_01"]["name"] == "Participant 2"
