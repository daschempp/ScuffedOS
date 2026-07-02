"""Google OAuth: authorize URL, code exchange, refresh, refresh-failure, revoke, profile sub.

No network: GoogleProvider.configure(fake_http=...) swaps the httpx call layer
(mirrors WhoopProvider). Google field/endpoint names are [confirm-against-live]
(M5 design §3, §13) — verified against the live Google/Gmail API during impl.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.providers.base import Tokens
from app.providers.google import (
    GOOGLE_AUTH_URL,
    GOOGLE_REVOKE_URL,
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    GoogleAuthError,
    GoogleProvider,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeHttp:
    """Records POSTs/GETs; replays scripted responses keyed by URL."""

    def __init__(self, responses):
        self.responses = responses         # {url: FakeResp}
        self.posts = []                    # [(url, data)]
        self.gets = []                     # [(url, params)]

    def post(self, url, data=None, **kw):
        self.posts.append((url, data))
        return self.responses.get(url, FakeResp(404, {}))

    def get(self, url, headers=None, params=None):
        self.gets.append((url, params))
        return self.responses.get(url, FakeResp(404, {}))


def _provider():
    settings.google_client_id = "gid"
    settings.google_client_secret = "gsecret"
    settings.google_redirect_uri = "http://localhost:8000/auth/google/callback"
    return GoogleProvider()


def test_authorize_url_has_all_oauth_params_and_offline_consent():
    p = _provider()
    url = p.authorize_url("st8tevalue")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == GOOGLE_AUTH_URL
    q = parse_qs(parsed.query)
    assert q["client_id"] == ["gid"]
    assert q["redirect_uri"] == ["http://localhost:8000/auth/google/callback"]
    assert q["response_type"] == ["code"]
    assert q["scope"] == [GOOGLE_SCOPES]
    assert q["state"] == ["st8tevalue"]
    # Google-specific: these two guarantee a refresh_token is issued.
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]


def test_scopes_include_openid_email_profile_and_gmail_readonly():
    # The frozen scope string — read-only Gmail plus identity for the sub.
    assert GOOGLE_SCOPES == (
        "openid email profile https://www.googleapis.com/auth/gmail.readonly"
    )


def test_exchange_code_returns_tokens():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {
            "access_token": "AT", "refresh_token": "RT",
            "expires_in": 3600, "scope": GOOGLE_SCOPES,
        }),
    }))
    tok = p.exchange_code("thecode")
    assert tok.access_token == "AT"
    assert tok.refresh_token == "RT"
    assert tok.scopes == GOOGLE_SCOPES
    assert tok.expires_at is not None and tok.expires_at.tzinfo is not None
    # exchange posted grant_type=authorization_code with the code + redirect_uri + secret
    url, data = p._http.posts[0]
    assert url == GOOGLE_TOKEN_URL
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "thecode"
    assert data["redirect_uri"] == settings.google_redirect_uri
    assert data["client_id"] == "gid"
    assert data["client_secret"] == "gsecret"


def test_refresh_rotates_access_and_keeps_old_refresh_when_omitted():
    p = _provider()
    # Google commonly omits refresh_token on refresh — keep the old one.
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {"access_token": "AT2", "expires_in": 3600}),
    }))
    tok = Tokens("old", "oldRT", None, scopes=GOOGLE_SCOPES)
    fresh = p.refresh(tok)
    assert fresh.access_token == "AT2"
    assert fresh.refresh_token == "oldRT"      # preserved
    assert fresh.scopes == GOOGLE_SCOPES        # preserved
    url, data = p._http.posts[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "oldRT"
    assert data["client_id"] == "gid"
    assert data["client_secret"] == "gsecret"


def test_refresh_uses_new_refresh_token_when_google_returns_one():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {
            "access_token": "AT2", "refresh_token": "RT2", "expires_in": 3600,
        }),
    }))
    fresh = p.refresh(Tokens("old", "oldRT", None))
    assert fresh.refresh_token == "RT2"


def test_refresh_failure_raises_google_auth_error():
    p = _provider()
    p.configure(fake_http=FakeHttp({GOOGLE_TOKEN_URL: FakeResp(400, {})}))
    with pytest.raises(GoogleAuthError):
        p.refresh(Tokens("old", "oldRT", None))


def test_refresh_without_refresh_token_raises():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))
    with pytest.raises(GoogleAuthError):
        p.refresh(Tokens("old", None, None))


def test_revoke_posts_to_revoke_url():
    p = _provider()
    p.configure(fake_http=FakeHttp({GOOGLE_REVOKE_URL: FakeResp(200, {})}))
    p.revoke(Tokens("AT", "RT", None))
    url, data = p._http.posts[0]
    assert url == GOOGLE_REVOKE_URL
    assert data["token"] == "AT"


def test_revoke_swallows_errors():
    """Disconnect must delete local data even if remote revoke fails (design §3/§7)."""
    p = _provider()
    p.configure(fake_http=FakeHttp({GOOGLE_REVOKE_URL: FakeResp(500, {})}))
    p.revoke(Tokens("AT", "RT", None))  # no raise


def test_google_auth_error_is_an_auth_error_subclass():
    """The email sync engine catches `except AuthError`; GoogleAuthError must be one."""
    from app.providers.base import AuthError
    assert issubclass(GoogleAuthError, AuthError)


def test_fetch_profile_returns_google_sub_as_provider_user_id():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_USERINFO_URL: FakeResp(200, {"sub": "108124972", "email": "a@b.com"}),
    }))
    uid = p.fetch_profile(Tokens("AT", "RT", None))
    assert uid == "108124972"                     # stringified Google sub
    assert p._http.gets[0][0] == GOOGLE_USERINFO_URL


def test_fetch_profile_failure_returns_none():
    p = _provider()
    p.configure(fake_http=FakeHttp({}))            # 404 default → best-effort None
    assert p.fetch_profile(Tokens("AT", "RT", None)) is None


def test_success_redirect_targets_the_email_screen():
    assert GoogleProvider().success_redirect() == "/?screen=email&connected=google"


def test_name_and_no_kind_attr():
    p = GoogleProvider()
    assert p.name == "google"
    # No `kind` → naturally excluded from pull_providers() (fitness sync).
    assert getattr(p, "kind", None) is None


def test_real_registry_includes_google():
    import importlib.util

    from app import providers
    providers.configure()  # real registry
    try:
        if importlib.util.find_spec("app.providers.google") is None:
            return  # module not authored yet (defensive; it exists in this phase)
        names = [pr.name for pr in providers.all_providers()]
        assert "google" in names
        assert providers.get("google") is not None
        assert providers.get("google").name == "google"
        # google has no `kind`, so it is NOT a pull (fitness) provider.
        assert "google" not in [pr.name for pr in providers.pull_providers()]
    finally:
        providers.configure([])  # restore the conftest test default (no external services)
