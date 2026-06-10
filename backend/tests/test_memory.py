SEED_COUNT = 4


def test_list_returns_seed_memories(client):
    res = client.get("/api/memory")
    assert res.status_code == 200
    memories = res.json()
    assert len(memories) == SEED_COUNT
    assert memories[0]["id"] == 1
    assert set(memories[0]) == {"id", "text", "src", "tags", "color", "when"}


def test_create_memory_applies_defaults(client):
    res = client.post("/api/memory", json={"text": "Passport renewal takes 6 weeks"})
    assert res.status_code == 201
    memory = res.json()
    assert memory["id"] == SEED_COUNT + 1
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


def test_create_memory_requires_text(client):
    res = client.post("/api/memory", json={})
    assert res.status_code == 422
