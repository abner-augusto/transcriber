from fastapi.testclient import TestClient
import pytest

import main


@pytest.fixture
def frontend(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<main>Transcriber UI</main>", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log('ui')", encoding="utf-8")
    monkeypatch.setattr(main, "_frontend_dist", dist)
    monkeypatch.setattr("preferences.public", lambda: {"default_vocabulary": ""})
    return TestClient(main.app)


def test_root_client_routes_and_assets_serve_the_built_frontend(frontend):
    assert frontend.get("/").text == "<main>Transcriber UI</main>"
    assert frontend.get("/meetings/example").text == "<main>Transcriber UI</main>"
    assert frontend.get("/assets/index-abc.js").text == "console.log('ui')"
    assert frontend.get("/api/settings").json() == {"preferences": {"default_vocabulary": ""}}


@pytest.mark.parametrize("path", ["/api/no-such-route", "/assets/missing.js"])
def test_unknown_api_routes_and_missing_assets_are_not_found(frontend, path):
    response = frontend.get(path)

    assert response.status_code == 404
    assert "Transcriber UI" not in response.text
