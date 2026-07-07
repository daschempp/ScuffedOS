"""M8 Ship/Tauri: a bare-root GET /health for the Tauri health-gate. Distinct
from the existing /api/health (which the frontend Vite proxy reaches). This
one is DB-free so it flips to 200 the moment uvicorn is up."""


def test_ship_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_existing_api_health_unchanged(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "scuffed-os-api"}
