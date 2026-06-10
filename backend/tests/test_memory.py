def test_create_memory_applies_defaults(client):
    res = client.post("/api/memory", json={"text": "Passport renewal takes 6 weeks"})
    assert res.status_code == 201
    memory = res.json()
    assert set(memory) == {"id", "text", "src", "tags", "color", "when",
                           "created_at", "updated_at"}
    assert memory["src"] == "note"
    assert memory["tags"] == []
    assert memory["color"] == "green"
    assert memory["when"] == "just now"

    memories = client.get("/api/memory").json()
    assert memories[0] == memory  # newest first


def test_create_memory_with_explicit_fields(client):
    res = client.post(
        "/api/memory",
        json={"text": "Gym closes at 10pm", "src": "voice note", "tags": ["health"], "color": "sky"},
    )
    assert res.status_code == 201
    memory = res.json()
    assert memory["src"] == "voice note"
    assert memory["tags"] == ["health"]
    assert memory["color"] == "sky"


def test_update_memory(client):
    memory = client.post("/api/memory", json={"text": "Gym closes at 10pm"}).json()
    res = client.patch(f"/api/memory/{memory['id']}", json={
        "text": "Gym closes at 11pm on weekdays", "tags": ["health", "schedule"],
    })
    assert res.status_code == 200
    updated = res.json()
    assert updated["text"] == "Gym closes at 11pm on weekdays"
    assert updated["tags"] == ["health", "schedule"]
    assert updated["color"] == "green"  # untouched


def test_delete_memory(client):
    memory = client.post("/api/memory", json={"text": "Forget me"}).json()
    assert client.delete(f"/api/memory/{memory['id']}").status_code == 204
    assert client.get("/api/memory").json() == []
    assert client.delete(f"/api/memory/{memory['id']}").status_code == 404


def test_update_unknown_memory_is_404(client):
    assert client.patch("/api/memory/999", json={"text": "x"}).status_code == 404


def test_create_memory_requires_text(client):
    assert client.post("/api/memory", json={}).status_code == 422
    assert client.post("/api/memory", json={"text": ""}).status_code == 422
