"""WHOOP OAuth router (M4): connect URL, callback, disconnect, status.

Every test installs a FakeProvider via providers.configure([...]) — no network.
The CSRF state store is the fitness router's in-process dict.
"""
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app import providers
from app.providers.base import Tokens
from app.routers import fitness
from app.store import store

from .fakes import FakeProvider


def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def test_connect_returns_authorize_url_with_client_id_and_state(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/fitness/connect/whoop")
    assert res.status_code == 200
    url = res.json()["authorize_url"]
    assert "client_id=fake-client" in url
    qs = parse_qs(urlparse(url).query)
    assert qs["state"][0]  # a non-empty state made it into the URL


def test_connect_stores_a_one_time_state_server_side(client):
    providers.configure([FakeProvider()])
    state = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    # The issued state is recorded server-side, mapped to its provider.
    assert fitness._STATES.get(state) == "whoop"
    # A second connect issues a fresh, distinct state (not reused).
    state2 = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    assert state2 != state


def test_connect_unknown_provider_is_404(client):
    providers.configure([FakeProvider()])  # only 'whoop' registered
    res = client.get("/api/fitness/connect/garmin")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_status_empty_when_nothing_connected(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/fitness/status")
    assert res.status_code == 200
    body = res.json()
    assert body == {"connected": False, "providers": []}


def test_status_reflects_a_connected_account_without_tokens(client):
    providers.configure([FakeProvider()])
    store.upsert_provider_account(
        "whoop",
        Tokens(
            access_token="secret-access",
            refresh_token="secret-refresh",
            expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            scopes="read:recovery",
            provider_user_id="whoop-user-1",
        ),
    )
    body = client.get("/api/fitness/status").json()
    assert body["connected"] is True
    assert len(body["providers"]) == 1
    p = body["providers"][0]
    assert p["provider"] == "whoop"
    assert p["status"] == "connected"
    assert p["provider_user_id"] == "whoop-user-1"
    assert p["last_sync_at"] is None
    # Tokens must never reach the client.
    assert "secret-access" not in res_text(body)
    assert "access_token" not in p and "refresh_token" not in p


def res_text(obj) -> str:
    import json
    return json.dumps(obj)


def test_callback_exchanges_persists_and_triggers_immediate_sync(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    ticks: list[object] = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: ticks.append(now) or 0)

    state = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    res = client.get(
        f"/auth/whoop/callback?code=the-code&state={state}",
        follow_redirects=False,
    )
    assert res.status_code in (302, 307)
    loc = res.headers["location"]
    assert "screen=fitness" in loc and "connected=whoop" in loc

    # The code was exchanged exactly once and the account was persisted.
    assert fake.exchanged == ["the-code"]
    accounts = store.list_provider_accounts()
    assert [a["provider"] for a in accounts] == ["whoop"]
    assert accounts[0]["status"] == "connected"
    assert accounts[0]["provider_user_id"] == "whoop-user-1"
    # An immediate sync (backfill) was triggered once.
    assert len(ticks) == 1
    # The state was one-time: it is gone from the store.
    assert state not in fitness._STATES


def test_callback_with_bad_state_is_400_and_persists_nothing(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)

    res = client.get(
        "/auth/whoop/callback?code=x&state=forged-state",
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "bad_request"
    assert fake.exchanged == []
    assert store.list_provider_accounts() == []


def test_callback_state_is_single_use(client, monkeypatch):
    from app import fitness_sync

    providers.configure([FakeProvider()])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/fitness/connect/whoop").json()["authorize_url"])
    first = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert first.status_code in (302, 307)
    # Replaying the same state must now fail — it was consumed.
    replay = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert replay.status_code == 400
