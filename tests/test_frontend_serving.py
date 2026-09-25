from pathlib import Path

from fastapi.testclient import TestClient

import main


def test_root_and_client_routes_serve_the_frontend(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<main>Transcriber UI</main>", encoding="utf-8")
    monkeypatch.setattr(main, "_frontend_dist", dist)

    client = TestClient(main.app)
    assert client.get("/").text == "<main>Transcriber UI</main>"
    assert client.get("/meetings/example").text == "<main>Transcriber UI</main>"
    actual_asset = next((Path(__file__).parent.parent / "frontend" / "dist" / "assets").iterdir())
    assert client.get(f"/assets/{actual_asset.name}").status_code == 200


def test_settings_api_route_precedes_frontend_fallback(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("frontend", encoding="utf-8")
    monkeypatch.setattr(main, "_frontend_dist", dist)
    monkeypatch.setattr("preferences.public", lambda: {"default_vocabulary": ""})

    response = TestClient(main.app).get("/api/settings")
    assert response.json() == {"preferences": {"default_vocabulary": ""}}
