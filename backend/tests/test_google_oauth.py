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
