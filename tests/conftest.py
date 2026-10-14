import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import jobs
from jobs.runners import InProcessBus, InlineJobRunner
from main import app
from presets import list_presets

NEMOTRON_SMOKE = {"id": "nemotron-3-diarization", "engine": "nemotron-3-diarization", "model_path": "./models/nemotron-diarization", "diarizer": True}
SMOKE_TARGETS = [*list_presets(), NEMOTRON_SMOKE]


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
    known = {preset["id"] for preset in SMOKE_TARGETS}
    unknown = sorted(set(_selected_ids(config)) - known)
    if unknown:
        raise pytest.UsageError(
            "unknown Engine smoke Preset(s): " + ", ".join(unknown)
        )


@pytest.fixture(autouse=True)
def _startup_leaves_storage_alone(monkeypatch):
    """Keep test clients off the real DB and the production runner lifecycle."""
    import main

    monkeypatch.setattr(main, "cleanup_orphaned_storage", lambda: None)
    monkeypatch.setattr(main.app.router, "on_startup", [])
    monkeypatch.setattr(main.app.router, "on_shutdown", [])


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    runner = InlineJobRunner(handlers={})
    bus = InProcessBus()
    previous = jobs.configure(
        runner=runner, progress_bus=bus, session_factory=TestingSessionLocal
    )
    app.state.test_job_runner = runner
    app.state.test_progress_bus = bus

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.clear()
        jobs.configure(**previous)
        del app.state.test_job_runner
        del app.state.test_progress_bus


@pytest.fixture
def isolated_preferences(monkeypatch, tmp_path):
    """Keep a route that reads Preferences (split, unsplit) off the real preferences file."""
    import config
    import preferences

    monkeypatch.setattr(config.settings, "storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(preferences, "LEGACY_PREFERENCES_PATH", tmp_path / "no-legacy-file")


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
    return next(preset for preset in SMOKE_TARGETS if preset["id"] == preset_id)


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


READY_PRESET = {"id": "ready", "name": "Ready", "engine": "parakeet.cpp", "model_path": "m"}


@pytest.fixture
def ready_engines(monkeypatch, tmp_path):
    """A client whose Preset and Diarizer are usable and whose storage is a temp folder."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr("config.settings.storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _id: READY_PRESET)
    monkeypatch.setattr("api.meetings.presets.get_preset", lambda _id: READY_PRESET)
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: type(
        "Ready", (), {"to_dict": lambda self: {"state": "ready", "summary": "ready"}})())
    monkeypatch.setattr("api.meetings._require_usable_diarizer", lambda: {"state": "ready"})
    return TestClient(app)
