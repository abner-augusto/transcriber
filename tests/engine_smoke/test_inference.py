import pytest

from presets import list_presets


@pytest.mark.model_inference
@pytest.mark.parametrize(
    "selected_engine_smoke_preset",
    [preset["id"] for preset in list_presets()],
    indirect=True,
)
def test_selected_preset_satisfies_word_and_turn_contracts(
    selected_engine_smoke_preset, engine_smoke_audio
):
    from scripts.engine_smoke import infer_preset, release_engine_memory

    try:
        result = infer_preset(selected_engine_smoke_preset, engine_smoke_audio)
        assert result["status"] == "passed"
        assert result["word_count"] > 0
    finally:
        release_engine_memory()
