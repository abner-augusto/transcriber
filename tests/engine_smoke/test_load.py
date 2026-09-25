import pytest

from presets import list_presets


@pytest.mark.model_load
@pytest.mark.parametrize(
    "selected_engine_smoke_preset",
    [preset["id"] for preset in list_presets()],
    indirect=True,
)
def test_selected_preset_loads_from_local_artifacts_only(selected_engine_smoke_preset):
    from scripts.engine_smoke import load_preset

    result = load_preset(selected_engine_smoke_preset)
    assert result["status"] == "passed"
