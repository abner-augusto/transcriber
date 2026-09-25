import math

import pytest

from engine_runtimes.protocol import EngineRequest, EngineResponse, ProtocolError


def request_dict():
    return {"schema_version": 1, "engine_id": "qwen3-asr", "audio_path": "C:/áudio/reunião.wav",
            "vocabulary": "Garrah", "model_path": "C:/modelos/qwen", "aligner_path": None,
            "device": "cuda", "options": {"language": "Portuguese", "chunk_seconds": 300.0}}


def response_dict():
    return {"schema_version": 1, "words": [{"start": 0.0, "end": 1.0, "text": " Olá", "confidence": .9, "alignment_score": .5}],
            "native_diarization": {"turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]},
            "diagnostics": {"alignment": "fallback"}, "runtime_fingerprint": "abc", "error": None}


def test_protocol_round_trip_preserves_unicode_words_and_turns():
    request = EngineRequest.from_dict(request_dict())
    response = EngineResponse.from_dict(response_dict())
    assert EngineRequest.from_dict(request.to_dict()) == request
    assert EngineResponse.from_dict(response.to_dict()) == response


def test_protocol_defaults_legacy_request_to_transcribe_and_accepts_load():
    assert EngineRequest.from_dict(request_dict()).operation == "transcribe"
    value = request_dict(); value["operation"] = "load"
    assert EngineRequest.from_dict(value).operation == "load"


def test_diarize_request_and_empty_words_turn_response_round_trip():
    value = request_dict()
    value.update(engine_id="nemotron-3-diarization", operation="diarize", vocabulary=None,
                 model_path="C:/models/nemotron")
    value["options"] = {"threshold": 0.5}
    assert EngineRequest.from_dict(value).operation == "diarize"
    response = response_dict()
    response["words"] = []
    parsed = EngineResponse.from_dict(response)
    assert parsed.words == () and len(parsed.native_turns) == 1
    assert EngineResponse.from_dict(parsed.to_dict()) == parsed


def test_diarize_rejects_other_engine_and_invalid_threshold():
    value = request_dict(); value["operation"] = "diarize"
    with pytest.raises(ProtocolError): EngineRequest.from_dict(value)
    value = request_dict(); value.update(engine_id="nemotron-3-diarization", operation="diarize")
    value["options"] = {"threshold": 2}
    with pytest.raises(ProtocolError): EngineRequest.from_dict(value)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(schema_version=2),
    lambda d: d.update(extra=True),
    lambda d: d.update(audio_path="relative.wav"),
])
def test_request_rejects_unknown_version_fields_and_relative_paths(mutation):
    value = request_dict(); mutation(value)
    with pytest.raises(ProtocolError): EngineRequest.from_dict(value)


@pytest.mark.parametrize("words", [
    [{"start": math.nan, "end": 1.0, "text": " x", "confidence": None, "alignment_score": None}],
    [{"start": 2.0, "end": 1.0, "text": " x", "confidence": None, "alignment_score": None}],
    [{"start": 2.0, "end": 3.0, "text": " x", "confidence": None, "alignment_score": None},
     {"start": 1.0, "end": 2.0, "text": " y", "confidence": None, "alignment_score": None}],
])
def test_response_rejects_nonfinite_invalid_and_unordered_words(words):
    value = response_dict(); value["words"] = words
    with pytest.raises(ProtocolError): EngineResponse.from_dict(value)
