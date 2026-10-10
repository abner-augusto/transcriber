import pytest

from tests.conftest import SMOKE_TARGETS


@pytest.mark.model_inference
@pytest.mark.parametrize(
    "selected_engine_smoke_preset",
    [preset["id"] for preset in SMOKE_TARGETS],
    indirect=True,
)
def test_selected_preset_satisfies_word_and_turn_contracts(
    selected_engine_smoke_preset, engine_smoke_audio
):
    if selected_engine_smoke_preset.get("diarizer"):
        from config import settings
        from engines.isolated_python import IsolatedPythonDiarizer
        from preferences import DiarizationPrefs
        diarizer = IsolatedPythonDiarizer(
            model_path=settings.nemotron_diarization_model_path,
            device=settings.nemotron_diarization_device,
            threshold=DiarizationPrefs().speech_threshold,
            min_speaker_seconds=DiarizationPrefs().min_speaker_seconds,
        )
        turns = diarizer.diarize(str(engine_smoke_audio)).turns
        assert turns
    else:
        from scripts.engine_smoke import infer_preset
        result = infer_preset(selected_engine_smoke_preset, engine_smoke_audio)
        assert result["status"] == "passed"
        assert result["word_count"] > 0
