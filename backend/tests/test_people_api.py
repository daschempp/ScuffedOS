from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import Person
from app.store import store

# NB: no local DB fixture here — tests/conftest.py's autouse `fresh_db` already
# binds `store` to a clean schema (with StaticPool, so the sqlite in-memory
# connection is actually shared) before every test; a second ad-hoc
# `create_engine("sqlite://")` fixture would just clobber that with a
# non-shared in-memory engine and every table lookup would 500.


def _insert_imported(**over):
    fields = dict(owner=settings.owner, source="macos_contacts", source_id="src-1",
                  display_name="Imported Person", phones=[], emails=[], meta={})
    fields.update(over)
    with store._session() as s, s.begin():
        row = Person(**fields)
        s.add(row)
        s.flush()
        return row.id


def test_manual_crud_roundtrip():
    c = TestClient(app)
    assert c.get("/api/people").json() == {"items": [], "next_cursor": None}
    created = c.post("/api/people", json={"display_name": "Ada Lovelace"}).json()
    assert created["source"] == "manual"
    pid = created["id"]
    patched = c.patch(f"/api/people/{pid}", json={"relationship": "Friend"}).json()
    assert patched["relationship"] == "Friend"
    assert c.get(f"/api/people/{pid}").json()["display_name"] == "Ada Lovelace"
    assert c.delete(f"/api/people/{pid}").status_code == 204
    assert c.get(f"/api/people/{pid}").status_code == 404


def test_imported_identity_is_read_only_but_crm_native_editable():
    c = TestClient(app)
    pid = _insert_imported()
    # identity edit rejected...
    assert c.patch(f"/api/people/{pid}", json={"display_name": "Hacked"}).status_code == 409
    assert c.patch(f"/api/people/{pid}", json={"emails": [{"value": "x@y.com"}]}).status_code == 409
    # ...CRM-native edit allowed
    ok = c.patch(f"/api/people/{pid}", json={"pinned": True, "notes": "met at PyCon"})
    assert ok.status_code == 200
    assert ok.json()["pinned"] is True
    # imported rows can't be hard-deleted individually
    assert c.delete(f"/api/people/{pid}").status_code == 409


def test_list_pagination_and_search():
    c = TestClient(app)
    for name in ("Al", "Bo", "Cy", "Di"):
        c.post("/api/people", json={"display_name": name})
    page1 = c.get("/api/people", params={"limit": 2}).json()
    assert [p["display_name"] for p in page1["items"]] == ["Al", "Bo"]
    assert page1["next_cursor"]
    page2 = c.get("/api/people", params={"limit": 2, "cursor": page1["next_cursor"]}).json()
    assert [p["display_name"] for p in page2["items"]] == ["Cy", "Di"]
    assert page2["next_cursor"] is None
    hit = c.get("/api/people", params={"q": "cy"}).json()
    assert [p["display_name"] for p in hit["items"]] == ["Cy"]


def test_sync_endpoint_returns_syncresult_shape(monkeypatch):
    from app import contacts_sync
    from app.store import SyncResult

    monkeypatch.setattr(contacts_sync, "tick",
                        lambda now=None: SyncResult(status="ok", access="granted",
                                                    imported=3, updated=1, removed=0))
    body = TestClient(app).post("/api/people/sync").json()
    assert body["status"] == "ok"
    assert body["access"] == "granted"
    assert body["imported"] == 3 and body["updated"] == 1


def test_enable_requires_ack_then_kicks_sync(monkeypatch):
    from app import contacts_sync
    from app.store import SyncResult

    called = {"n": 0}

    def fake_tick(now=None):
        called["n"] += 1
        return SyncResult(status="ok", access="granted")

    monkeypatch.setattr(contacts_sync, "tick", fake_tick)
    c = TestClient(app)
    assert c.post("/api/people/contacts/enable", json={}).status_code == 400  # no ack
    body = c.post("/api/people/contacts/enable",
                  json={"ack_storage_disclosure": True}).json()
    assert body["enabled"] is True
    assert body["normalization_region"] == settings.contacts_default_region
    assert called["n"] == 1                                                  # sync kicked


def test_disconnect_preserves_rows():
    c = TestClient(app)
    _insert_imported()
    body = c.post("/api/people/contacts/disconnect").json()
    assert body["enabled"] is False
    assert body["status"] == "disabled"
    assert len(c.get("/api/people").json()["items"]) == 1                    # row kept


def test_forget_requires_confirm_and_applies_tombstone_rule():
    c = TestClient(app)
    keep = _insert_imported(source_id="keep", display_name="Has CRM", notes="best man")
    drop = _insert_imported(source_id="drop", display_name="No CRM")
    assert c.post("/api/people/contacts/forget", json={}).status_code == 400  # no confirm
    c.post("/api/people/contacts/forget", json={"confirm": True})
    kept = c.get(f"/api/people/{keep}").json()
    assert kept["source"] == "manual"           # converted to a tombstone
    assert kept["display_name"] == "Has CRM"
    assert kept["notes"] == "best man"
    assert c.get(f"/api/people/{drop}").status_code == 404   # fully deleted


def test_photo_endpoint_serves_detected_type_and_guards_traversal(monkeypatch, tmp_path):
    photos = tmp_path / "contact_photos"
    photos.mkdir()
    # `contacts_photos_root` is a *method* on the pydantic Settings model, not a
    # field, so it can't be monkeypatched directly (pydantic rejects setting
    # non-field attributes). Point the underlying field at an absolute path
    # instead — contacts_photos_root() returns it as-is when absolute (see
    # providers/contact_photos.resolve_root).
    monkeypatch.setattr(settings, "contacts_photos_dir", str(photos))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    (photos / "pic.png").write_bytes(png)
    c = TestClient(app)
    pid = _insert_imported(photo_key="pic.png", has_photo=True)
    r = c.get(f"/api/people/{pid}/photo")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # missing key -> 404
    nokey = _insert_imported(source_id="np", photo_key=None)
    assert c.get(f"/api/people/{nokey}/photo").status_code == 404
    # traversal attempt -> 404 (containment check)
    evil = _insert_imported(source_id="ev", photo_key="../secret.png", has_photo=True)
    (tmp_path / "secret.png").write_bytes(png)
    assert c.get(f"/api/people/{evil}/photo").status_code == 404
