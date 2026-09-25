"""Tests for vocabulary profile CRUD and participant cleaning."""

import pytest
from fastapi.testclient import TestClient

from main import app
import preferences


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A client whose Preferences file lives in a temporary storage directory."""
    import config

    monkeypatch.setattr(config.settings, "storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(preferences, "LEGACY_PREFERENCES_PATH", tmp_path / "no-legacy-file")
    yield TestClient(app)


def test_list_profiles_empty(client):
    resp = client.get("/api/preferences/vocabulary-profiles")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_profile(client):
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Dev / Engineering", "terms": "Docker, Kubernetes, gRPC, Celery, Redis, PyTorch, PR"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Dev / Engineering"
    assert data["terms"] == "Docker, Kubernetes, gRPC, Celery, Redis, PyTorch, PR"
    assert data["id"]


def test_create_profile_duplicate_name(client):
    client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Dev", "terms": "Docker"},
    )
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "dev", "terms": "Kubernetes"},
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


def test_create_profile_requires_name(client):
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "", "terms": "Docker"},
    )
    assert resp.status_code == 400


def test_create_profile_requires_terms(client):
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Dev", "terms": ""},
    )
    assert resp.status_code == 400


def test_list_profiles_after_create(client):
    client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Dev", "terms": "Docker, Kubernetes"},
    )
    client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Business", "terms": "CAC, LTV, churn"},
    )
    resp = client.get("/api/preferences/vocabulary-profiles")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_update_profile_name(client):
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Dev", "terms": "Docker"},
    )
    profile_id = resp.json()["id"]

    resp = client.put(f"/api/preferences/vocabulary-profiles/{profile_id}", json={"name": "Engineering"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Engineering"
    assert resp.json()["terms"] == "Docker"


def test_update_profile_terms(client):
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Dev", "terms": "Docker"},
    )
    profile_id = resp.json()["id"]

    resp = client.put(f"/api/preferences/vocabulary-profiles/{profile_id}", json={"terms": "Docker, Kubernetes, gRPC"})
    assert resp.status_code == 200
    assert resp.json()["terms"] == "Docker, Kubernetes, gRPC"


def test_update_profile_not_found(client):
    resp = client.put("/api/preferences/vocabulary-profiles/nonexistent", json={"name": "X"})
    assert resp.status_code == 404


def test_delete_profile(client):
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Dev", "terms": "Docker"},
    )
    profile_id = resp.json()["id"]

    resp = client.delete(f"/api/preferences/vocabulary-profiles/{profile_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp = client.get("/api/preferences/vocabulary-profiles")
    assert resp.json() == []


def test_delete_profile_not_found(client):
    resp = client.delete("/api/preferences/vocabulary-profiles/nonexistent")
    assert resp.status_code == 404


def test_profile_terms_truncated_to_2000(client):
    long_terms = "a" * 3000
    resp = client.post(
        "/api/preferences/vocabulary-profiles",
        json={"name": "Long", "terms": long_terms},
    )
    assert resp.status_code == 200
    assert len(resp.json()["terms"]) == 2000
