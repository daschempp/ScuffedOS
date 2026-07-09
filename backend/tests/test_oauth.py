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

from .fakes import FakeEmailProvider, FakeProvider


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
    stored = oauth._STATES.get(state)
    assert isinstance(stored, tuple) and stored[0] == "whoop" and isinstance(stored[1], str) and stored[1]
    state2 = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    assert state2 != state


def test_connect_derives_s256_challenge_from_the_stored_verifier(client):
    import base64
    import hashlib

    class ChallengeSpy(FakeProvider):
        def __init__(self):
            super().__init__()
            self.seen_challenge = "MISSING"

        def authorize_url(self, state, code_challenge=None):
            self.seen_challenge = code_challenge
            return super().authorize_url(state)

    spy = ChallengeSpy()
    providers.configure([spy])
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    verifier = oauth._STATES[state][1]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert spy.seen_challenge == expected


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


def test_callback_success_renders_html_and_persists_and_syncs(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    ticks: list[object] = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: ticks.append(now) or 0)

    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?code=the-code&state={state}", follow_redirects=False)
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "close this tab" in res.text.lower()

    assert fake.exchanged == ["the-code"]
    accounts = store.list_provider_accounts()
    assert [a["provider"] for a in accounts] == ["whoop"]
    assert accounts[0]["status"] == "connected"
    assert accounts[0]["provider_user_id"] == "whoop-user-1"
    assert len(ticks) == 1                 # WhoopProvider.on_connected -> fitness_sync.tick
    assert state not in oauth._STATES


def test_callback_success_persists_even_when_on_connected_hook_raises(client, monkeypatch):
    """A post-persist on_connected() failure (e.g. the domain sync tick blowing
    up) must NOT flip an already-successful connect into an error page — the
    account row is committed before on_connected runs, so the user is
    connected either way. Regression for the M9 s1 final-review Fix B: the old
    code wrapped exchange+persist+on_connected in ONE try/except."""
    from app import fitness_sync

    class HookBoom(FakeProvider):
        def on_connected(self) -> None:
            raise RuntimeError("sync tick exploded")

    fake = HookBoom()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)

    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?code=the-code&state={state}", follow_redirects=False)

    assert res.status_code == 200
    assert "close this tab" in res.text.lower()
    accounts = store.list_provider_accounts()
    assert [a["provider"] for a in accounts] == ["whoop"]
    assert accounts[0]["status"] == "connected"


def test_callback_passes_stored_verifier_into_exchange(client):
    class VerifierSpy(FakeProvider):
        def __init__(self):
            super().__init__()
            self.seen_verifier = "MISSING"

        def exchange_code(self, code, verifier=None):
            self.seen_verifier = verifier
            return super().exchange_code(code)

    spy = VerifierSpy()
    providers.configure([spy])
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    stored_verifier = oauth._STATES[state][1]
    res = client.get(f"/auth/whoop/callback?code=the-code&state={state}", follow_redirects=False)
    assert res.status_code == 200
    assert spy.seen_verifier == stored_verifier


def test_callback_exchange_failure_renders_error_and_persists_nothing(client, monkeypatch):
    """exchange_code raising (network blip, bad code) is a pre-persist failure —
    must render the error page and leave no account row behind. Closes a
    coverage gap: only the bad-state/access-denied/missing-code error paths
    were previously tested, not an actual exchange exception."""
    from app import fitness_sync

    class ExchangeBoom(FakeProvider):
        def exchange_code(self, code, verifier=None):
            raise RuntimeError("token endpoint 500")

    fake = ExchangeBoom()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)

    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?code=the-code&state={state}", follow_redirects=False)

    assert res.status_code == 400
    assert "text/html" in res.headers["content-type"]
    assert store.list_provider_accounts() == []


def test_callback_with_bad_state_renders_error_html_and_persists_nothing(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)

    res = client.get("/auth/whoop/callback?code=x&state=forged-state", follow_redirects=False)
    assert res.status_code == 400
    assert "text/html" in res.headers["content-type"]
    assert fake.exchanged == []
    assert store.list_provider_accounts() == []


def test_callback_state_is_single_use(client, monkeypatch):
    from app import fitness_sync

    providers.configure([FakeProvider()])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    first = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert first.status_code == 200
    replay = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert replay.status_code == 400   # state already consumed -> error page


def test_callback_access_denied_renders_error_without_422(client, monkeypatch):
    # Google's access_denied redirect carries error and NO code. The old
    # required `code` param would 422 before handler code ran; §6a must render
    # the inline error page instead. State is still consumed.
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?error=access_denied&state={state}", follow_redirects=False)
    assert res.status_code == 400
    assert "text/html" in res.headers["content-type"]
    assert fake.exchanged == []
    assert store.list_provider_accounts() == []
    assert state not in oauth._STATES        # consumed even on the error path


def test_callback_missing_code_renders_error(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?state={state}", follow_redirects=False)
    assert res.status_code == 400
    assert fake.exchanged == []


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


def test_status_surfaces_can_write_email_false_when_scopes_lack_write(client):
    providers.configure([FakeEmailProvider()])
    store.upsert_provider_account(
        "google",
        Tokens(
            access_token="a", refresh_token="r", expires_at=None,
            scopes="openid email https://www.googleapis.com/auth/gmail.readonly",
            provider_user_id="g1",
        ),
    )
    body = client.get("/api/oauth/status").json()
    p = body["providers"][0]
    assert p["provider"] == "google"
    assert p["can_write_email"] is False


def test_status_surfaces_can_write_email_true_when_modify_and_send_both_granted(client):
    providers.configure([FakeEmailProvider()])
    store.upsert_provider_account(
        "google",
        Tokens(
            access_token="a", refresh_token="r", expires_at=None,
            scopes=(
                "openid email profile "
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/gmail.modify "
                "https://www.googleapis.com/auth/gmail.send"
            ),
            provider_user_id="g1",
        ),
    )
    body = client.get("/api/oauth/status").json()
    p = body["providers"][0]
    assert p["can_write_email"] is True


def test_status_can_write_email_requires_both_scopes_not_just_one(client):
    providers.configure([FakeEmailProvider()])
    store.upsert_provider_account(
        "google",
        Tokens(
            access_token="a", refresh_token="r", expires_at=None,
            # modify only, no send — must NOT count as write-capable.
            scopes="openid email https://www.googleapis.com/auth/gmail.modify",
            provider_user_id="g1",
        ),
    )
    body = client.get("/api/oauth/status").json()
    assert body["providers"][0]["can_write_email"] is False
    # Raw scopes are still never serialized to the client (existing privacy rule).
    assert "scopes" not in body["providers"][0]
