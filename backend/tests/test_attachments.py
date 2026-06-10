"""Task file attachments (M3): bytes on disk, metadata on the task row."""
from io import BytesIO
from pathlib import Path

from app.config import settings


def _make_task(client, label: str = "Has files") -> dict:
    res = client.post("/api/tasks", json={"label": label})
    assert res.status_code == 201
    return res.json()


def _upload(client, task_id: int, name: str, data: bytes, ctype: str = "text/plain"):
    return client.post(
        f"/api/tasks/{task_id}/files", files={"file": (name, BytesIO(data), ctype)}
    )


def test_upload_returns_task_with_file_meta_and_writes_bytes(client):
    task = _make_task(client)
    res = _upload(client, task["id"], "notes.txt", b"remember the milk")
    assert res.status_code == 201
    updated = res.json()
    assert updated["id"] == task["id"]
    assert len(updated["files"]) == 1
    meta = updated["files"][0]
    file_id = meta["id"]
    assert isinstance(file_id, str) and len(file_id) == 32
    int(file_id, 16)  # uuid hex — parses as hexadecimal
    assert meta["name"] == "notes.txt"
    assert meta["size"] == len(b"remember the milk")
    on_disk = Path(settings.attachments_dir) / str(task["id"]) / file_id
    assert on_disk.read_bytes() == b"remember the milk"


def test_download_returns_exact_bytes_with_name_and_media_type(client):
    task = _make_task(client)
    body = b"alpha\nbeta\n"
    file_id = _upload(client, task["id"], "shopping-list.txt", body).json()["files"][0]["id"]
    res = client.get(f"/api/tasks/{task['id']}/files/{file_id}")
    assert res.status_code == 200
    assert res.content == body
    assert 'filename="shopping-list.txt"' in res.headers["content-disposition"]
    assert res.headers["content-type"].startswith("text/plain")


def test_download_404s_for_unknown_task_and_unknown_file(client):
    task = _make_task(client)
    res = client.get("/api/tasks/999/files/deadbeefdeadbeefdeadbeefdeadbeef")
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "not_found", "message": "Task not found"}}
    res = client.get(f"/api/tasks/{task['id']}/files/deadbeefdeadbeefdeadbeefdeadbeef")
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "not_found", "message": "File not found"}}


def test_upload_to_unknown_task_is_404(client):
    res = _upload(client, 999, "notes.txt", b"orphan")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_delete_file_removes_metadata_and_bytes(client):
    task = _make_task(client)
    file_id = _upload(client, task["id"], "old.txt", b"stale").json()["files"][0]["id"]
    on_disk = Path(settings.attachments_dir) / str(task["id"]) / file_id

    res = client.delete(f"/api/tasks/{task['id']}/files/{file_id}")
    assert res.status_code == 204
    listed = client.get("/api/tasks").json()
    assert next(t for t in listed if t["id"] == task["id"])["files"] == []
    assert not on_disk.exists()
    assert client.get(f"/api/tasks/{task['id']}/files/{file_id}").status_code == 404
    # Deleting again: the file is gone but the task isn't.
    assert client.delete(f"/api/tasks/{task['id']}/files/{file_id}").status_code == 404


def test_deleting_task_removes_its_attachment_directory(client):
    task = _make_task(client)
    _upload(client, task["id"], "doomed.txt", b"going down with the ship")
    task_dir = Path(settings.attachments_dir) / str(task["id"])
    assert task_dir.is_dir()
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert not task_dir.exists()


def test_same_filename_uploads_coexist_with_distinct_ids(client):
    task = _make_task(client)
    _upload(client, task["id"], "draft.txt", b"v1")
    files = _upload(client, task["id"], "draft.txt", b"v2 with more").json()["files"]
    assert len(files) == 2
    assert files[0]["id"] != files[1]["id"]
    assert {f["name"] for f in files} == {"draft.txt"}
    # Each id still serves its own bytes.
    by_size = {f["size"]: f["id"] for f in files}
    res = client.get(f"/api/tasks/{task['id']}/files/{by_size[len(b'v1')]}")
    assert res.content == b"v1"
    res = client.get(f"/api/tasks/{task['id']}/files/{by_size[len(b'v2 with more')]}")
    assert res.content == b"v2 with more"


def test_crafted_file_id_cannot_escape_the_attachments_root(client, tmp_path):
    """`files` metadata is client-patchable on the task row, so a crafted id
    must never resolve to a path outside the task's attachment dir."""
    from app.config import settings

    secret = tmp_path / "secret.txt"
    secret.write_text("not yours")
    task = client.post("/api/tasks", json={"label": "t"}).json()
    evil_id = f"../../../{secret.name}"
    # Plant matching metadata the way a hostile client would: via PATCH.
    res = client.patch(f"/api/tasks/{task['id']}",
                       json={"files": [{"id": evil_id, "name": "secret.txt"}]})
    assert res.status_code == 200

    res = client.get(f"/api/tasks/{task['id']}/files/{evil_id}")
    assert res.status_code == 404
    assert secret.exists()

    res = client.delete(f"/api/tasks/{task['id']}/files/{evil_id}")
    # Metadata entry is removed, but the file outside the root is untouched.
    assert res.status_code in (204, 404)
    assert secret.exists() and secret.read_text() == "not yours"
