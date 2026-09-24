import os

import pytest

from presets import list_presets


def pytest_addoption(parser):
    group = parser.getgroup("engine smoke")
    group.addoption(
        "--run-engine-smoke",
        action="store_true",
        help="run explicitly selected local-only Engine load/inference smoke tests",
    )
    group.addoption(
        "--engine-smoke-preset",
        action="append",
        default=[],
        metavar="PRESET_ID",
        help="Preset to smoke-test; repeat to select more than one (or use ENGINE_SMOKE_PRESETS)",
    )
    group.addoption(
        "--engine-smoke-audio",
        default=None,
        metavar="LOCAL_AUDIO",
        help="local audio file for model_inference (or use ENGINE_SMOKE_AUDIO)",
    )


def _selected_ids(config):
    command_line = config.getoption("--engine-smoke-preset")
    environment = [
        item.strip()
        for item in os.environ.get("ENGINE_SMOKE_PRESETS", "").split(",")
        if item.strip()
    ]
    return command_line or environment


def pytest_configure(config):
    # Keeps FastAPI startup away from the real storage directory.
    os.environ["TRANSCRIBER_TESTING"] = "1"
    known = {preset["id"] for preset in list_presets()}
    unknown = sorted(set(_selected_ids(config)) - known)
    if unknown:
        raise pytest.UsageError(
            "unknown Engine smoke Preset(s): " + ", ".join(unknown)
        )


@pytest.fixture
def selected_engine_smoke_preset(request):
    if not request.config.getoption("--run-engine-smoke"):
        pytest.skip("Engine smoke tests require explicit --run-engine-smoke opt-in")
    selected = _selected_ids(request.config)
    if not selected:
        pytest.skip("select a Preset with --engine-smoke-preset or ENGINE_SMOKE_PRESETS")
    preset_id = request.param
    if preset_id not in selected:
        pytest.skip(f"Preset {preset_id!r} was not selected for Engine smoke testing")
    return next(preset for preset in list_presets() if preset["id"] == preset_id)


@pytest.fixture
def engine_smoke_audio(request):
    from pathlib import Path

    configured = request.config.getoption("--engine-smoke-audio") or os.environ.get(
        "ENGINE_SMOKE_AUDIO"
    )
    if not configured:
        pytest.skip("model inference requires --engine-smoke-audio or ENGINE_SMOKE_AUDIO")
    path = Path(configured).expanduser().resolve()
    if not path.is_file():
        pytest.skip(f"configured local Engine smoke audio does not exist: {path}")
    return path
