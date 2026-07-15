"""M10 Slice 1 — GET /api/connectors macOS Contacts card (`auth_kind='local'`).

`_contacts_configured`/`_contacts_access` are stubbed directly on the
`connectors` module (rather than driving through `macos_contacts.configure`)
so these tests are deterministic regardless of host platform or FDA grant,
matching the pattern the brief specifies."""
from fastapi.testclient import TestClient

from app.main import app
from app.routers import connectors
from app.store import store


def _card(client):
    return next(c for c in client.get("/api/connectors").json()
               if c["name"] == "macos_contacts")


def _state(**over):
    base = {"enabled": False, "status": "disabled", "access": "unknown",
            "normalization_region": None, "enabled_at": None,
            "last_sync_at": None, "last_error": None}
    base.update(over)
    return base


def test_contacts_card_connected(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: True)
    monkeypatch.setattr(connectors, "_contacts_access", lambda: "granted")
    monkeypatch.setattr(store, "get_contacts_state",
                        lambda: _state(enabled=True, status="ready", access="granted"))
    card = _card(TestClient(app))
    assert card["auth_kind"] == "local"
    assert card["access"] == "granted"
    assert card["status"] == "connected"
    assert card["enabled"] is True
    assert card["sync_status"] == "ready"


def test_contacts_card_denied(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: True)
    monkeypatch.setattr(connectors, "_contacts_access", lambda: "denied")
    monkeypatch.setattr(store, "get_contacts_state", lambda: _state(enabled=True))
    card = _card(TestClient(app))
    assert card["access"] == "denied"
    assert card["status"] == "not_connected"
    assert card["enabled"] is True
    assert card["sync_status"] == "disabled"


def test_contacts_card_unsupported_off_darwin(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: False)
    card = _card(TestClient(app))
    assert card["configured"] is False
    assert card["access"] == "unknown"
    assert card["status"] == "not_connected"
    assert card["enabled"] is False
    assert card["sync_status"] is None


def test_contacts_card_count_is_imported_people(monkeypatch):
    """count reflects store.count_people(source="macos_contacts") when configured,
    and is never computed (None) when the card is unsupported."""
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: True)
    monkeypatch.setattr(connectors, "_contacts_access", lambda: "granted")
    monkeypatch.setattr(store, "get_contacts_state",
                        lambda: _state(enabled=True, status="ready", access="granted"))
    monkeypatch.setattr(store, "count_people", lambda source=None: 7)
    card = _card(TestClient(app))
    assert card["count"] == 7


def test_contacts_card_count_none_when_unsupported(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: False)
    card = _card(TestClient(app))
    assert card["count"] is None
