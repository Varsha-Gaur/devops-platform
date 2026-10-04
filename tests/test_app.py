import pytest

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_index(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.get_json()["service"] == "devops-platform-api"


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_ready_ok(client):
    assert client.get("/ready").status_code == 200


def test_health_broken_flag(client, monkeypatch):
    monkeypatch.setenv("BREAK_HEALTH", "true")
    assert client.get("/health").status_code == 500
    assert client.get("/ready").status_code == 503


def test_create_and_get_item(client):
    created = client.post("/api/items", json={"name": "book"})
    assert created.status_code == 201
    item_id = created.get_json()["id"]
    fetched = client.get(f"/api/items/{item_id}")
    assert fetched.status_code == 200
    assert fetched.get_json()["name"] == "book"


def test_create_item_validation(client):
    response = client.post("/api/items", json={})
    assert response.status_code == 400


def test_item_not_found(client):
    assert client.get("/api/items/999").status_code == 404


def test_list_items(client):
    client.post("/api/items", json={"name": "a"})
    response = client.get("/api/items")
    assert response.get_json()["count"] == 1


def test_simulated_error(client):
    assert client.get("/api/error").status_code == 500


def test_protected_requires_key(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    assert client.get("/api/protected").status_code == 401
    assert client.get("/api/protected", headers={"X-API-Key": "wrong"}).status_code == 401
    ok = client.get("/api/protected", headers={"X-API-Key": "test-key"})
    assert ok.status_code == 200


def test_protected_denied_when_key_not_configured(client, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    assert client.get("/api/protected", headers={"X-API-Key": ""}).status_code == 401


def test_metrics_exposed(client):
    client.get("/")
    body = client.get("/metrics").get_data(as_text=True)
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body