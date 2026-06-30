"""WhoopProvider — WHOOP v2 adapter (M4 design §4, §13).

Hand-rolled OAuth + authed REST over httpx (no Authlib; one provider doesn't
justify a dependency). All WHOOP field/endpoint names are confined to THIS
module — everything past it speaks the normalized dataclasses in base.py.

The http layer is a test seam mirroring llm.py: configure(fake_http=obj)
installs a fake exposing .post()/.get(); configure() (fake_http='unset')
restores the lazy real httpx.Client. Tokens are refreshed transparently when
within ~60s of expiry; a refresh failure raises WhoopAuthError, which the
sync engine/store translate into status='needs_reauth'.

CONFIRMED against the live v2 docs:
  auth   https://api.prod.whoop.com/oauth/oauth2/auth
  token  https://api.prod.whoop.com/oauth/oauth2/token
  base   https://api.prod.whoop.com/developer/v2/
  list responses: {"records": [...], "next_token": "..."}; query param nextToken
  metrics nested under a per-record "score" object; score_state in
          {"SCORED","PENDING_SCORE","UNSCORABLE"}
  workout sport field is "sport_name" in v2 (v1 used sport_id)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..config import settings
from .base import (
    AuthError,
    NormalizedSnapshot,
    NormalizedWorkout,
    Tokens,
)

log = logging.getLogger("scuffed_os.whoop")

# [confirm-against-live] — verified against WHOOP v2 docs during M4 impl.
WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_REVOKE_URL = "https://api.prod.whoop.com/oauth/oauth2/revoke"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2/"
WHOOP_PROFILE_PATH = "user/profile/basic"  # [confirm-against-live] basic-profile collection
WHOOP_SCOPES = "read:recovery read:sleep read:workout read:cycles read:profile offline"
KJ_TO_KCAL = 0.239006  # calories = round(kilojoule * KJ_TO_KCAL)

# Refresh when the access token is within this many seconds of expiring.
_REFRESH_SKEW = timedelta(seconds=60)


class WhoopAuthError(AuthError):
    """Token refresh/exchange failed irrecoverably — caller flips needs_reauth.

    Subclasses providers.base.AuthError (NOT RuntimeError) so the sync engine's
    `except AuthError` catches it and flips the provider to needs_reauth."""


class WhoopProvider:
    name = "whoop"
    kind = "pull"

    def __init__(self) -> None:
        self._http: object | str = "unset"   # 'unset' → lazy real httpx.Client
        self._client = None
        self._tokens: Tokens | None = None    # injected by the sync engine before fetch_*

    # ---- http seam (mirrors llm._override) ----
    def configure(self, fake_http: object | str = "unset") -> None:
        """Tests install a fake exposing .post()/.get(); configure() restores real."""
        self._http = fake_http
        self._client = None

    def set_tokens(self, tokens: Tokens | None) -> None:
        """The sync engine injects the stored (possibly-refreshed) tokens here
        before calling fetch_recovery/sleep/workouts so authed calls carry a
        Bearer token. Without this every fetch would 401 (empty token)."""
        self._tokens = tokens

    def _transport(self):
        if self._http != "unset":
            return self._http
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=20.0)
        return self._client

    # ---- OAuth ----
    def authorize_url(self, state: str) -> str:
        q = urlencode({
            "client_id": settings.whoop_client_id,
            "redirect_uri": settings.whoop_redirect_uri,
            "response_type": "code",
            "scope": WHOOP_SCOPES,
            "state": state,
        })
        return f"{WHOOP_AUTH_URL}?{q}"

    def _token_request(self, data: dict) -> Tokens:
        res = self._transport().post(WHOOP_TOKEN_URL, data=data)
        if getattr(res, "status_code", 200) >= 400:
            raise WhoopAuthError(f"WHOOP token endpoint returned {res.status_code}")
        payload = res.json()
        expires_at = None
        if payload.get("expires_in") is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(payload["expires_in"])
            )
        return Tokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            scopes=payload.get("scope", "") or "",
        )

    def exchange_code(self, code: str) -> Tokens:
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.whoop_redirect_uri,
            "client_id": settings.whoop_client_id,
            "client_secret": settings.whoop_client_secret,
        })

    def refresh(self, tokens: Tokens) -> Tokens:
        if not tokens.refresh_token:
            raise WhoopAuthError("no refresh_token on record")
        try:
            fresh = self._token_request({
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": settings.whoop_client_id,
                "client_secret": settings.whoop_client_secret,
                "scope": "offline",
            })
        except WhoopAuthError:
            raise
        except Exception as exc:  # network etc. — treat as reauth-needed
            raise WhoopAuthError(f"refresh failed: {exc}") from exc
        # WHOOP may not echo a new refresh_token — keep the old one if absent.
        if fresh.refresh_token is None:
            fresh.refresh_token = tokens.refresh_token
        if not fresh.scopes:
            fresh.scopes = tokens.scopes
        return fresh

    def _ensure_fresh(self, tokens: Tokens) -> Tokens:
        """Refresh transparently if within the skew of expiry; else pass through."""
        if tokens.expires_at is None:
            return tokens
        if datetime.now(timezone.utc) >= tokens.expires_at - _REFRESH_SKEW:
            return self.refresh(tokens)
        return tokens

    def revoke(self, tokens: Tokens) -> None:
        """Best-effort remote revoke; disconnect deletes local data regardless."""
        try:
            self._transport().post(
                WHOOP_REVOKE_URL,
                data={
                    "client_id": settings.whoop_client_id,
                    "client_secret": settings.whoop_client_secret,
                    "token": tokens.access_token,
                },
            )
        except Exception as exc:
            log.warning("WHOOP revoke failed (continuing): %s", exc)

    def fetch_profile(self, tokens: Tokens) -> str | None:
        """GET the WHOOP basic profile and return the provider user id.

        Called by the OAuth callback right after exchange_code so the account's
        provider_user_id is populated (it is NOT inferred from the token
        payload). Best-effort: a profile fetch failure returns None rather than
        blocking the connect — the id is non-critical metadata. The id field
        name is [confirm-against-live] (WHOOP v2 basic profile)."""
        try:
            res = self._transport().get(
                WHOOP_API_BASE + WHOOP_PROFILE_PATH,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                params=None,
            )
            if getattr(res, "status_code", 200) >= 400:
                log.warning("WHOOP profile returned %s", getattr(res, "status_code", "?"))
                return None
            body = res.json() or {}
            uid = body.get("user_id")
            return str(uid) if uid is not None else None
        except Exception as exc:
            log.warning("WHOOP profile fetch failed (continuing): %s", exc)
            return None

    # ---- pull (stubs; filled in next task) ----
    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]:
        return []

    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]:
        return []

    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]:
        return []
