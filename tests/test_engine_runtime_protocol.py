import math

import pytest

from engine_runtimes.protocol import EngineRequest, EngineResponse, ProtocolError
from engines.isolated_python import IsolatedPythonTranscriber


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


def test_isolated_adapter_preserves_native_turns_and_fingerprint(monkeypatch, tmp_path):
    model = tmp_path / "modelo"; model.mkdir()
    response = EngineResponse.from_dict(response_dict())
    monkeypatch.setattr("engines.isolated_python.launch_engine", lambda **kwargs: response)
    adapter = IsolatedPythonTranscriber(engine_id="vibevoice", model_path=str(model), aligner_path=None,
        device="cpu", options={"window_seconds": 600.0, "overlap_seconds": 45.0})
    words = adapter.transcribe(str(tmp_path / "áudio com espaço.wav"))
    assert words[0].text == " Olá"
    assert adapter.get_native_diarization().turns[0].speaker == "SPEAKER_00"
    assert adapter.runtime_fingerprint == "abc"
