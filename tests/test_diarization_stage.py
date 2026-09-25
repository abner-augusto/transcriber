"""The Diarization stage: how a Meeting gets its Turns, and the one shape they are stored in.

The snapshot tests run the real ``process_meeting_task`` and pin ``raw_diarization``
for each way a Meeting can be diarized. Stored Meetings are read back by
Reprocessing and the API, so these shapes are a contract, not an implementation
detail.
"""

import pytest

from engines import DiarizationResult, Turn
from models.job import JobType
from tasks.diarization import diarize_meeting
from tasks.process_meeting import process_meeting_task
from transcript.diarization import MeetingDiarization

from . import task_harness as h
from .fakes import FakeDiarizer


def _process(monkeypatch, tmp_path, transcriber, *, dual_track=False, **columns):
    harness = h.install(monkeypatch, tmp_path, transcriber=transcriber, diarization=h.PYANNOTE)
    meeting_id = harness.meeting(dual_track=dual_track, **columns)
    if dual_track:
        harness.write_dual_tracks(meeting_id)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    return harness, harness.load(meeting_id)


def _turn(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


SINGLE_TRACK_STORED = {
    "engine": "pyannote",
    "turns": [_turn(0.0, 2.0, "SPEAKER_00"), _turn(1.5, 4.0, "SPEAKER_01")],
    "exclusive_turns": [_turn(0.0, 1.5, "SPEAKER_00"), _turn(1.5, 4.0, "SPEAKER_01")],
    "original_turns": [_turn(0.0, 2.0, "SPEAKER_00"), _turn(1.5, 6.0, "SPEAKER_01")],
    "original_exclusive_turns": [_turn(0.0, 1.5, "SPEAKER_00"), _turn(1.5, 6.0, "SPEAKER_01")],
    "overlaps": [{"start": 1.5, "end": 2.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]}],
    "original_overlaps": [{"start": 1.5, "end": 2.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]}],
}

NATIVE_STORED = {
    "engine": "vibevoice",
    "turns": [_turn(0.0, 1.0, "SPEAKER_0"), _turn(1.0, 4.0, "SPEAKER_1")],
    "exclusive_turns": None,
    "original_turns": [_turn(0.0, 1.0, "SPEAKER_0"), _turn(1.0, 5.0, "SPEAKER_1")],
    "original_exclusive_turns": None,
    "overlaps": [],
    "original_overlaps": [],
}

DUAL_TRACK_STORED = {
    "engine": "pyannote",
    "turns": [
        _turn(0.0, 1.0, "HOST"),
        _turn(0.5, 2.0, "SPEAKER_00"),
        _turn(1.5, 3.0, "SPEAKER_01"),
    ],
    "exclusive_turns": [
        _turn(0.0, 0.5, "HOST"),
        _turn(1.0, 1.5, "SPEAKER_00"),
        _turn(2.0, 3.0, "SPEAKER_01"),
    ],
    "overlaps": [
        {"start": 0.5, "end": 1.0, "speakers": ["HOST", "SPEAKER_00"]},
        {"start": 1.5, "end": 2.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
    ],
    "host_label": "HOST",
}


def test_single_track_meeting_is_diarized_by_the_diarizer_and_bounded_by_vad(monkeypatch, tmp_path):
    harness, meeting = _process(monkeypatch, tmp_path, h.FakeTranscriber(h.WORDS))

    assert meeting.raw_diarization == SINGLE_TRACK_STORED
    assert [call[0] for call in harness.diarizer.calls] == [meeting.audio_filepath]
    segments = sorted(meeting.segments, key=lambda s: s.order)
    assert [(s.speaker.label, s.text) for s in segments] == [
        ("SPEAKER_00", "olá pessoal"),
        ("SPEAKER_01", "tudo"),
    ]


def test_native_turns_bypass_the_diarizer(monkeypatch, tmp_path):
    transcriber = h.NativeTranscriber(h.WORDS, h.NATIVE)
    harness, meeting = _process(monkeypatch, tmp_path, transcriber, preset_id="vibevoice-7b")

    assert meeting.raw_diarization == NATIVE_STORED
    assert harness.diarizer.calls == []


def test_dual_track_meeting_names_the_mic_host_and_diarizes_only_the_system_track(monkeypatch, tmp_path):
    harness, meeting = _process(
        monkeypatch, tmp_path, h.FakeTranscriber(h.WORDS),
        dual_track=True, min_speakers=1, max_speakers=3,
    )

    assert meeting.raw_diarization == DUAL_TRACK_STORED
    assert len(harness.diarizer.calls) == 1
    path, min_speakers, max_speakers = harness.diarizer.calls[0]
    assert path.endswith("system_processed.wav")
    assert (min_speakers, max_speakers) == (1, 3)
    host = next(s for s in meeting.speakers if s.label == "HOST")
    assert (host.display_name, host.identified_by) == ("You", "host_track")


def test_dual_track_wins_over_native_turns(monkeypatch, tmp_path):
    transcriber = h.NativeTranscriber(h.WORDS, h.NATIVE)
    harness, meeting = _process(monkeypatch, tmp_path, transcriber, dual_track=True, preset_id="vibevoice-7b")

    assert meeting.raw_diarization["host_label"] == "HOST"
    assert meeting.raw_diarization["engine"] == "pyannote"
    assert len(harness.diarizer.calls) == 1


# --- MeetingDiarization: the stored shape --------------------------------------------


@pytest.mark.parametrize("stored", [SINGLE_TRACK_STORED, NATIVE_STORED, DUAL_TRACK_STORED])
def test_every_stored_shape_round_trips(stored):
    assert MeetingDiarization.from_stored(stored).to_stored() == stored


def test_empty_storage_reads_as_no_diarization():
    assert MeetingDiarization.from_stored(None) is None
    assert MeetingDiarization.from_stored({}) is None
    assert MeetingDiarization.from_stored([]) is None


def test_legacy_bare_list_reads_as_turns_with_computed_overlaps():
    diarization = MeetingDiarization.from_stored(
        [_turn(0.0, 2.0, "SPEAKER_00"), _turn(1.0, 3.0, "SPEAKER_01")]
    )

    assert diarization.turns == [
        Turn(start=0.0, end=2.0, speaker="SPEAKER_00"),
        Turn(start=1.0, end=3.0, speaker="SPEAKER_01"),
    ]
    assert diarization.exclusive_turns is None
    assert diarization.overlaps == [{"start": 1.0, "end": 2.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]}]
    assert diarization.host_label is None


def test_stored_dict_without_exclusive_turns_or_overlaps_still_reads():
    diarization = MeetingDiarization.from_stored(
        {"engine": "pyannote", "turns": [_turn(0.0, 2.0, "A"), _turn(1.0, 3.0, "B")]}
    )

    assert diarization.exclusive_turns is None
    assert diarization.overlaps == [{"start": 1.0, "end": 2.0, "speakers": ["A", "B"]}]
    assert diarization.attribution_turns == diarization.turns


def test_attribution_prefers_exclusive_turns_and_falls_back_when_empty():
    stored = MeetingDiarization.from_stored(SINGLE_TRACK_STORED)
    assert stored.attribution_turns == stored.exclusive_turns

    empty_exclusive = MeetingDiarization.from_stored({**SINGLE_TRACK_STORED, "exclusive_turns": []})
    assert empty_exclusive.attribution_turns == empty_exclusive.turns


def test_speaker_labels_cover_turns_and_exclusive_turns():
    diarization = MeetingDiarization(
        engine="pyannote",
        turns=[Turn(start=0.0, end=1.0, speaker="B")],
        exclusive_turns=[Turn(start=0.0, end=1.0, speaker="A")],
        overlaps=[],
    )
    assert diarization.speaker_labels == ["A", "B"]


# --- diarize_meeting: which way a Meeting gets its Turns ------------------------------


class _Meeting:
    def __init__(self, *, dual_track=False, min_speakers=None, max_speakers=None):
        self.id = "meeting-1"
        self.is_dual_track = dual_track
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers


class _Vad:
    def compute_vad_segments(self, path):
        return [(0.0, 10.0)]

    def mask_turns_to_vad(self, turns, segments):
        return list(turns)


def test_single_track_calls_the_diarizer_with_the_speaker_bounds():
    diarizer = FakeDiarizer([Turn(start=0.0, end=1.0, speaker="SPEAKER_00")])
    reported = []

    diarization = diarize_meeting(
        _Meeting(min_speakers=2, max_speakers=4), "audio.wav", diarizer=diarizer,
        vad_service=_Vad(), on_path=reported.append,
    )

    assert diarizer.calls == [("audio.wav", 2, 4)]
    assert diarization.engine == "pyannote"
    assert diarization.host_label is None
    assert reported == ["diarizer"]


def test_native_turns_are_bounded_without_calling_the_diarizer():
    diarizer = FakeDiarizer([])
    native = DiarizationResult(
        turns=[Turn(start=0.0, end=1.0, speaker="SPEAKER_0")], engine="vibevoice"
    )
    reported = []

    diarization = diarize_meeting(
        _Meeting(), "audio.wav", diarizer=diarizer, vad_service=_Vad(),
        native=native, on_path=reported.append,
    )

    assert diarizer.calls == []
    assert diarization.engine == "vibevoice"
    assert diarization.turns == native.turns
    assert diarization.original_turns == native.turns
    assert reported == ["native"]


def test_dual_track_without_processed_tracks_names_the_missing_file(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config.settings, "storage_path", str(tmp_path))
    diarizer = FakeDiarizer([])

    with pytest.raises(RuntimeError, match="mic_processed.wav"):
        diarize_meeting(_Meeting(dual_track=True), "mixed.wav", diarizer=diarizer, vad_service=_Vad())
    assert diarizer.calls == []
