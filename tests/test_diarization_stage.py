"""The Diarization stage: how a Meeting gets its Turns, and the one shape they are stored in.

The snapshot tests run the real ``process_meeting_task`` and pin ``raw_diarization``
for each way a Meeting can be diarized. Stored Meetings are read back by
Reprocessing and the API, so these shapes are a contract, not an implementation
detail.
"""

from models.job import JobType
from tasks.process_meeting import process_meeting_task

from . import task_harness as h


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
