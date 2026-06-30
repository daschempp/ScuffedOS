"""WHOOP OAuth: authorize URL, code exchange, refresh-near-expiry, refresh failure, revoke.

No network: WhoopProvider.configure(fake_http=...) swaps the httpx call layer.
WHOOP field/endpoint names are [confirm-against-live] (M4 design §13) — verified
against the live v2 docs during implementation.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.providers.base import Tokens
from app.providers.whoop import (
    WHOOP_API_BASE,
    WHOOP_AUTH_URL,
    WHOOP_PROFILE_PATH,
    WHOOP_REVOKE_URL,
    WHOOP_SCOPES,
    WHOOP_TOKEN_URL,
    WhoopAuthError,
    WhoopProvider,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class FakeHttp:
    """Records POSTs/GETs; replays scripted responses keyed by URL."""

    def __init__(self, responses):
        self.responses = responses        # {url: FakeResp}
        self.posts = []                    # [(url, data)]
        self.gets = []                     # [(url, params)]

    def post(self, url, data=None, **kw):
        self.posts.append((url, data))
        return self.responses.get(url, FakeResp(404, {}))

    def get(self, url, headers=None, params=None):
        self.gets.append((url, params))
        return self.responses.get(url, FakeResp(404, {}))


def _provider():
    settings.whoop_client_id = "cid"
    settings.whoop_client_secret = "secret"
    settings.whoop_redirect_uri = "https://example.test/auth/whoop/callback"
    return WhoopProvider()


def test_authorize_url_has_all_oauth_params():
    p = _provider()
    url = p.authorize_url("st8tevalue")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == WHOOP_AUTH_URL
    q = parse_qs(parsed.query)
    assert q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["https://example.test/auth/whoop/callback"]
    assert q["response_type"] == ["code"]
    assert q["scope"] == [WHOOP_SCOPES]
    assert q["state"] == ["st8tevalue"]


def test_exchange_code_returns_tokens():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        WHOOP_TOKEN_URL: FakeResp(200, {
            "access_token": "AT", "refresh_token": "RT",
            "expires_in": 3600, "scope": WHOOP_SCOPES,
        }),
    }))
    tok = p.exchange_code("thecode")
    assert tok.access_token == "AT"
    assert tok.refresh_token == "RT"
    assert tok.scopes == WHOOP_SCOPES
    assert tok.expires_at is not None and tok.expires_at.tzinfo is not None
    # exchange posted grant_type=authorization_code with the code + redirect_uri
    url, data = p._http.posts[0]
    assert url == WHOOP_TOKEN_URL
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "thecode"
    assert data["redirect_uri"] == settings.whoop_redirect_uri


def test_refresh_when_near_expiry_rotates_tokens():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        WHOOP_TOKEN_URL: FakeResp(200, {
            "access_token": "AT2", "refresh_token": "RT2", "expires_in": 3600,
        }),
    }))
    soon = datetime.now(timezone.utc) + timedelta(seconds=30)  # within 60s guard
    tok = Tokens("old", "oldRT", soon, scopes=WHOOP_SCOPES)
    fresh = p.refresh(tok)
    assert fresh.access_token == "AT2"
    assert fresh.refresh_token == "RT2"
    url, data = p._http.posts[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "oldRT"


def test_refresh_failure_raises_whoop_auth_error():
    p = _provider()
    p.configure(fake_http=FakeHttp({WHOOP_TOKEN_URL: FakeResp(401, {})}))
    soon = datetime.now(timezone.utc) + timedelta(seconds=10)
    with pytest.raises(WhoopAuthError):
        p.refresh(Tokens("old", "oldRT", soon))


def test_refresh_without_refresh_token_raises():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))
    soon = datetime.now(timezone.utc) + timedelta(seconds=10)
    with pytest.raises(WhoopAuthError):
        p.refresh(Tokens("old", None, soon))


def test_revoke_posts_to_revoke_url():
    p = _provider()
    p.configure(fake_http=FakeHttp({WHOOP_REVOKE_URL: FakeResp(200, {})}))
    p.revoke(Tokens("AT", "RT", None))
    assert p._http.posts[0][0] == WHOOP_REVOKE_URL


def test_revoke_swallows_errors():
    """Disconnect must delete local data even if remote revoke fails (design §7)."""
    p = _provider()
    p.configure(fake_http=FakeHttp({WHOOP_REVOKE_URL: FakeResp(500, {})}))
    p.revoke(Tokens("AT", "RT", None))  # no raise


def test_whoop_auth_error_is_an_auth_error_subclass():
    """The sync engine catches `except AuthError`; WhoopAuthError must be one."""
    from app.providers.base import AuthError
    assert issubclass(WhoopAuthError, AuthError)


def test_fetch_profile_returns_provider_user_id():
    p = _provider()
    profile_url = WHOOP_API_BASE + WHOOP_PROFILE_PATH
    p.configure(fake_http=FakeHttp({
        profile_url: FakeResp(200, {"user_id": 10129, "first_name": "Sam"}),
    }))
    uid = p.fetch_profile(Tokens("AT", "RT", None))
    assert uid == "10129"                       # stringified WHOOP user id
    assert p._http.gets[0][0] == profile_url     # hit the basic-profile path


def test_fetch_profile_failure_returns_none():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))          # 404 default → best-effort None
    assert p.fetch_profile(Tokens("AT", "RT", None)) is None


def test_provider_conforms_to_protocol():
    from app.providers.base import FitnessProvider
    assert isinstance(_provider(), FitnessProvider)
    assert _provider().name == "whoop"
    assert _provider().kind == "pull"
