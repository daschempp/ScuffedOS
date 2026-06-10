def test_404_uses_error_envelope(client):
    res = client.patch("/api/tasks/999", json={"done": True})
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "not_found", "message": "Task not found"}}


def test_validation_error_uses_envelope_with_details(client):
    res = client.post("/api/tasks", json={})
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"]
    assert isinstance(body["error"]["details"], list)


def test_unknown_route_uses_envelope(client):
    res = client.get("/api/nonexistent")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
