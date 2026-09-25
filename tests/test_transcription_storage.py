"""Characterize the stored raw_transcription contract at the task boundary."""

import pytest

from engines import DiarizationResult, Transcription, Turn, Word, raw_transcription
from models.job import JobType
from tasks.process_meeting import process_meeting_task

from . import task_harness as h
from .fakes import FakeTranscriber


class RuntimeTranscriber(FakeTranscriber):
    def transcribe(self, audio_path, vocabulary=None):
        result = super().transcribe(audio_path, vocabulary)
        return Transcription(
            words=result.words,
            provenance={"runtime": {
                "fingerprint": "runtime-fingerprint",
                "diagnostics": {"runtime": "ready"},
            }},
        )


class DtwTranscriber(FakeTranscriber):
    def transcribe(self, audio_path, vocabulary=None):
        result = super().transcribe(audio_path, vocabulary)
        return Transcription(words=result.words, provenance={"dtw": "large-v3"})


@pytest.mark.parametrize(
    ("transcriber_type", "extra"),
    [
        (FakeTranscriber, {}),
        (RuntimeTranscriber, {"runtime": {
            "fingerprint": "runtime-fingerprint",
            "diagnostics": {"runtime": "ready"},
        }}),
        (DtwTranscriber, {"dtw": "large-v3"}),
    ],
)
def test_process_task_keeps_the_existing_raw_transcription_shape(
    monkeypatch, tmp_path, transcriber_type, extra
):
    words = [Word(0.1, 0.5, " hello", 0.9)]
    transcriber = transcriber_type(words)
    harness = h.install(
        monkeypatch,
        tmp_path,
        transcriber=transcriber,
        diarization=DiarizationResult(turns=[Turn(0.0, 1.0, "SPEAKER_00")]),
    )
    meeting_id = harness.meeting()
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)

    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    assert transcriber.lifecycle == ["load", "transcribe", "unload"]

    meeting = harness.load(meeting_id)
    assert meeting.raw_transcription == {
        "engine": "whisper.cpp",
        "preset": "whisper-large-v3-turbo",
        "words": [words[0].to_dict()],
        **extra,
    }


def test_raw_transcription_rejects_adapter_owned_reserved_keys():
    with pytest.raises(ValueError, match="reserved key.*engine"):
        raw_transcription(
            "whisper.cpp",
            "whisper-large-v3-turbo",
            Transcription(words=[], provenance={"engine": "wrong-owner"}),
        )
