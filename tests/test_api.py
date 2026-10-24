from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_json_liveness_status():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"].startswith("application/json")
