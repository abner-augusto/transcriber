import pytest

from tests.conftest import SMOKE_TARGETS


@pytest.mark.model_load
@pytest.mark.parametrize(
    "selected_engine_smoke_preset",
    [preset["id"] for preset in SMOKE_TARGETS],
    indirect=True,
)
def test_selected_preset_loads_from_local_artifacts_only(selected_engine_smoke_preset):
    if selected_engine_smoke_preset.get("diarizer"):
        from config import settings
        from engines.isolated_python import IsolatedPythonDiarizer
        IsolatedPythonDiarizer(model_path=settings.nemotron_diarization_model_path, device="cuda").load()
        return
    from scripts.engine_smoke import load_preset

    result = load_preset(selected_engine_smoke_preset)
    assert result["status"] == "passed"
