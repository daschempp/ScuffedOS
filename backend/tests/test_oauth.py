"""Shared OAuth router (M5): connect URL, callback, disconnect, status.

Moved from test_fitness_oauth.py — the M4 guardrail now drives /api/oauth/*
instead of /api/fitness/*. The callback path /auth/whoop/callback is unchanged
(it lives on oauth.auth_router now). Every test installs a FakeProvider via
providers.configure([...]) — no network. The CSRF state store is oauth._STATES.
"""
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app import providers
from app.providers.base import Tokens
from app.routers import oauth
from app.store import store

from .fakes import FakeProvider


def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def res_text(obj) -> str:
    return json.dumps(obj)


def test_connect_returns_authorize_url_with_client_id_and_state(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/oauth/connect/whoop")
    assert res.status_code == 200
    url = res.json()["authorize_url"]
    assert "client_id=fake-client" in url
    qs = parse_qs(urlparse(url).query)
    assert qs["state"][0]


def test_connect_stores_a_one_time_state_server_side(client):
    providers.configure([FakeProvider()])
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    assert oauth._STATES.get(state) == "whoop"
    state2 = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    assert state2 != state


def test_connect_unknown_provider_is_404(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/oauth/connect/garmin")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_status_empty_when_nothing_connected(client):
    providers.configure([FakeProvider()])
    res = client.get("/api/oauth/status")
    assert res.status_code == 200
    assert res.json() == {"connected": False, "providers": []}


def test_status_reflects_a_connected_account_without_tokens(client):
    providers.configure([FakeProvider()])
    store.upsert_provider_account(
        "whoop",
        Tokens(
            access_token="secret-access", refresh_token="secret-refresh",
            expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            scopes="read:recovery", provider_user_id="whoop-user-1",
        ),
    )
    body = client.get("/api/oauth/status").json()
    assert body["connected"] is True
    assert len(body["providers"]) == 1
    p = body["providers"][0]
    assert p["provider"] == "whoop"
    assert p["status"] == "connected"
    assert p["provider_user_id"] == "whoop-user-1"
    assert p["last_sync_at"] is None
    assert "secret-access" not in res_text(body)
    assert "access_token" not in p and "refresh_token" not in p


def test_callback_exchanges_persists_and_triggers_immediate_sync(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    ticks: list[object] = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: ticks.append(now) or 0)

    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(
        f"/auth/whoop/callback?code=the-code&state={state}",
        follow_redirects=False,
    )
    assert res.status_code in (302, 307)
    loc = res.headers["location"]
    assert "screen=fitness" in loc and "connected=whoop" in loc

    assert fake.exchanged == ["the-code"]
    accounts = store.list_provider_accounts()
    assert [a["provider"] for a in accounts] == ["whoop"]
    assert accounts[0]["status"] == "connected"
    assert accounts[0]["provider_user_id"] == "whoop-user-1"
    # on_connected() ran WhoopProvider.on_connected → fitness_sync.tick once.
    assert len(ticks) == 1
    assert state not in oauth._STATES


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
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    first = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert first.status_code in (302, 307)
    replay = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert replay.status_code == 400


def test_disconnect_revokes_then_deletes_and_returns_status(client):
    fake = FakeProvider()
    providers.configure([fake])
    store.upsert_provider_account(
        "whoop",
        Tokens(access_token="a", refresh_token="r", expires_at=None,
               scopes="read:recovery", provider_user_id="u1"),
    )
    assert client.get("/api/oauth/status").json()["connected"] is True

    res = client.post("/api/oauth/disconnect/whoop")
    assert res.status_code == 200
    assert res.json() == {"connected": False, "providers": []}
    assert len(fake.revoked) == 1
    assert fake.revoked[0].access_token == "a"
    assert store.list_provider_accounts() == []


def test_disconnect_deletes_even_when_revoke_fails(client):
    class Boom(FakeProvider):
        def revoke(self, tokens):
            raise RuntimeError("whoop revoke endpoint down")

    providers.configure([Boom()])
    store.upsert_provider_account(
        "whoop",
        Tokens(access_token="a", refresh_token="r", expires_at=None,
               scopes="", provider_user_id=None),
    )
    res = client.post("/api/oauth/disconnect/whoop")
    assert res.status_code == 200
    assert res.json()["connected"] is False
    assert store.list_provider_accounts() == []


def test_disconnect_unknown_provider_is_404(client):
    providers.configure([FakeProvider()])
    res = client.post("/api/oauth/disconnect/whoop")  # nothing connected
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_fitness_oauth_routes_are_removed(client):
    # The OAuth surface moved to /api/oauth/*; /api/fitness/connect|status|
    # disconnect must no longer be routable.
    providers.configure([FakeProvider()])
    assert client.get("/api/fitness/connect/whoop").status_code == 404
    assert client.get("/api/fitness/status").status_code == 404
    assert client.post("/api/fitness/disconnect/whoop").status_code == 404
