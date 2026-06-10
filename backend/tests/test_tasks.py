SEED_COUNT = 5


def test_list_returns_seed_tasks(client):
    res = client.get("/api/tasks")
    assert res.status_code == 200
    tasks = res.json()
    assert len(tasks) == SEED_COUNT
    assert tasks[0] == {"id": 1, "label": "Pay rent", "done": True}
    assert all(set(t) == {"id", "label", "done"} for t in tasks)


def test_create_task_defaults_and_ordering(client):
    res = client.post("/api/tasks", json={"label": "Water the plants"})
    assert res.status_code == 201
    task = res.json()
    assert task == {"id": SEED_COUNT + 1, "label": "Water the plants", "done": False}

    tasks = client.get("/api/tasks").json()
    assert len(tasks) == SEED_COUNT + 1
    assert tasks[0] == task  # newest first


def test_create_task_can_start_done(client):
    res = client.post("/api/tasks", json={"label": "Already handled", "done": True})
    assert res.status_code == 201
    assert res.json()["done"] is True


def test_patch_toggles_done_without_label(client):
    res = client.patch("/api/tasks/2", json={"done": True})
    assert res.status_code == 200
    assert res.json() == {"id": 2, "label": "Reply to Priya about Lighthouse", "done": True}


def test_patch_updates_label_only(client):
    res = client.patch("/api/tasks/3", json={"label": "Log dinner"})
    assert res.status_code == 200
    body = res.json()
    assert body["label"] == "Log dinner"
    assert body["done"] is False


def test_patch_unknown_task_is_404(client):
    res = client.patch("/api/tasks/999", json={"done": True})
    assert res.status_code == 404


def test_create_task_requires_label(client):
    res = client.post("/api/tasks", json={})
    assert res.status_code == 422
