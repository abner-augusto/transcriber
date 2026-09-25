from engine_runtimes.protocol import EngineResponse
from engines.isolated_python import IsolatedPythonTranscriber


def _response():
    return EngineResponse(
        words=(),
        native_turns=(),
        diagnostics={"alignment": "fallback"},
        runtime_fingerprint="runtime-abc",
    )


def test_isolated_adapter_returns_native_words_and_runtime_provenance(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    response = EngineResponse.from_dict({
        "schema_version": 1,
        "words": [{
            "start": 0.0, "end": 1.0, "text": " Olá",
            "confidence": 0.9, "alignment_score": 0.5,
        }],
        "native_diarization": {
            "turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
        },
        "diagnostics": {"alignment": "fallback"},
        "runtime_fingerprint": "abc",
        "error": None,
    })
    monkeypatch.setattr("engines.isolated_python.launch_engine", lambda **kwargs: response)
    adapter = IsolatedPythonTranscriber(
        engine_id="vibevoice", model_path=str(model), aligner_path=None,
        device="cpu", options={"window_seconds": 600.0, "overlap_seconds": 45.0},
    )

    transcription = adapter.transcribe(str(tmp_path / "audio.wav"))

    assert transcription.words[0].text == " Olá"
    assert transcription.native.turns[0].speaker == "SPEAKER_00"
    assert transcription.provenance == {
        "runtime": {
            "fingerprint": "abc",
            "diagnostics": {"alignment": "fallback"},
        }
    }


def test_isolated_adapter_load_keeps_protocol_v1_operation(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    captured = {}

    def launch(**kwargs):
        captured["request"] = kwargs["request"]
        return _response()

    monkeypatch.setattr("engines.isolated_python.launch_engine", launch)
    adapter = IsolatedPythonTranscriber(
        engine_id="qwen3-asr", model_path=str(model), aligner_path=None,
        device="cpu", options={},
    )

    adapter.load()

    assert captured["request"].operation == "load"
