"""Shared OAuth router (M5) — provider-registry-driven connect/callback/
disconnect/status, extracted from routers/fitness.py so a second OAuth domain
(email) reuses the plumbing. Domain-specific behavior lives behind the
OAuthProvider hooks: success_redirect (where to land), on_connected (kick the
domain sync), on_disconnect (delete the domain's data). Tokens never leave the
server.

Two routers are exported: `router` under /api/oauth, and `auth_router` with NO
prefix so a provider-registered redirect lands at exactly /auth/{provider}/
callback (outside /api). main.py includes both.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from .. import providers
from ..schemas import ConnectUrl, OAuthStatus
from ..store import store
# Lazy import helper — imported at call time to avoid circular reference
# (fitness imports providers; this avoids an import-time cycle).
def _fitness_states() -> "dict[str, str]":
    from . import fitness  # noqa: PLC0415 — deferred to avoid cycles
    return fitness._STATES

router = APIRouter(prefix="/api/oauth", tags=["oauth"])
auth_router = APIRouter(tags=["oauth"])

# One-time CSRF states: state token -> provider name. In-process is fine for a
# single-user desktop app (one-time CSRF check); a restart mid-flow just makes
# the user click Connect again.
_STATES: dict[str, str] = {}

logger = logging.getLogger("scuffed_os.oauth")


def _issue_state(provider: str) -> str:
    state = secrets.token_urlsafe(24)
    _STATES[state] = provider
    return state


def _consume_state(state: str) -> str | None:
    """Pop a state, returning the provider it was issued for (one-time use).
    Falls back to fitness._STATES so both the /api/oauth/connect and
    /api/fitness/connect paths work with a single callback route."""
    result = _STATES.pop(state, None)
    if result is None:
        # During coexistence (Task 5), the fitness connect endpoint stores
        # states in fitness._STATES; fall back there so test_fitness_oauth
        # passes even when oauth.auth_router is included first.
        result = _fitness_states().pop(state, None)
    return result


def _status_dict() -> dict:
    accounts = store.list_provider_accounts()
    return {
        "connected": any(a["status"] == "connected" for a in accounts),
        "providers": accounts,
    }


@router.get("/connect/{provider}", response_model=ConnectUrl)
def connect(provider: str) -> dict:
    """Build the provider's authorize URL with a fresh one-time CSRF state."""
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    state = _issue_state(provider)
    return {"authorize_url": impl.authorize_url(state)}


@router.get("/status", response_model=OAuthStatus)
def status() -> dict:
    """Per-provider connection state. Reads safe dicts only — no tokens."""
    return _status_dict()


@auth_router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """OAuth redirect target (outside /api). Verify the one-time CSRF state,
    exchange the code, best-effort stamp the provider_user_id, persist tokens
    server-side, run the provider's post-connect hook (an immediate domain
    sync/backfill), then bounce back to the provider's screen."""
    issued_for = _consume_state(state)
    if issued_for is None or issued_for != provider:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    tokens = impl.exchange_code(code)
    # exchange_code does NOT carry provider_user_id. Fetch it from the
    # provider's profile endpoint (best-effort) and stamp it onto the tokens.
    fetch_profile = getattr(impl, "fetch_profile", None)
    if fetch_profile is not None and tokens.provider_user_id is None:
        uid = fetch_profile(tokens)
        if uid is not None:
            tokens.provider_user_id = uid
    store.upsert_provider_account(provider, tokens)
    impl.on_connected()   # immediate domain sync/backfill (fresh account → backfill)
    return RedirectResponse(impl.success_redirect(), status_code=302)


@router.post("/disconnect/{provider}", response_model=OAuthStatus)
def disconnect(provider: str) -> dict:
    """Revoke at the provider (best-effort), delete its tokens (+ any fitness
    data via delete_provider_data), then run the provider's on_disconnect hook
    to clear its domain data. Deletion is the user-facing guarantee, so a
    failed revoke never blocks it. A missing account → 404."""
    impl = providers.get(provider)
    tokens = store.get_provider_tokens(provider)
    if impl is not None and tokens is not None:
        try:
            impl.revoke(tokens)
        except Exception as exc:  # noqa: BLE001 — revoke is best-effort
            logger.warning("revoke failed for %s, deleting anyway: %s", provider, exc)
    # delete_provider_data removes the account row (+ fitness tables where
    # source==provider); its existed return drives the 404.
    if not store.delete_provider_data(provider):
        raise HTTPException(status_code=404, detail=f"No connected '{provider}' account")
    # on_disconnect clears the provider's domain data. For WHOOP this re-calls
    # delete_provider_data (idempotent — row already gone); for Google it
    # deletes the emails table. Best-effort so a hook error never 500s the
    # user-facing delete.
    if impl is not None:
        try:
            impl.on_disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("on_disconnect hook failed for %s: %s", provider, exc)
    return _status_dict()
