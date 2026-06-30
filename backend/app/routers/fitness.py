"""Fitness endpoints (M4) — WHOOP OAuth + normalized reads/writes.

The read/write surface (/today, /workouts, /week) lands in a later phase;
this module owns the OAuth dance: connect (build authorize URL + issue a
one-time CSRF state), the callback (verify state -> exchange -> persist ->
immediate sync), disconnect (revoke best-effort -> delete provider data),
and per-provider status. Tokens never leave the server.

Two routers are exported: `router` under /api/fitness, and `auth_router`
with NO prefix so the WHOOP-registered redirect lands at exactly
/auth/{provider}/callback (outside /api). main.py includes both.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from .. import fitness_sync, providers
from ..schemas import ConnectUrl, FitnessStatus
from ..store import store

router = APIRouter(prefix="/api/fitness", tags=["fitness"])
auth_router = APIRouter(tags=["fitness-oauth"])

# One-time CSRF states: state token -> provider name. In-process is fine for
# a single-user desktop app (the spec's "stored server-side, one-time CSRF
# check"); a process restart mid-flow just makes the user click Connect again.
_STATES: dict[str, str] = {}

logger = logging.getLogger("scuffed_os.fitness")


def _issue_state(provider: str) -> str:
    state = secrets.token_urlsafe(24)
    _STATES[state] = provider
    return state


def _consume_state(state: str) -> str | None:
    """Pop a state, returning the provider it was issued for (one-time use)."""
    return _STATES.pop(state, None)


@router.get("/connect/{provider}", response_model=ConnectUrl)
def connect(provider: str) -> dict:
    """Build the provider's authorize URL with a fresh one-time CSRF state."""
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    state = _issue_state(provider)
    return {"authorize_url": impl.authorize_url(state)}


@router.get("/status", response_model=FitnessStatus)
def status() -> dict:
    """Per-provider connection state. Reads safe dicts only — no tokens."""
    accounts = store.list_provider_accounts()
    return {
        "connected": any(a["status"] == "connected" for a in accounts),
        "providers": accounts,
    }


# Redirect target after a successful connect — the SPA reads screen/connected.
_FITNESS_REDIRECT = "/?screen=fitness&connected={provider}"


@auth_router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """OAuth redirect target (outside /api). Verify the one-time CSRF state,
    exchange the code, fetch the profile id, persist tokens server-side, kick
    off an immediate sync+backfill, then bounce back to the Fitness screen."""
    issued_for = _consume_state(state)
    if issued_for is None or issued_for != provider:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    impl = providers.get(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    tokens = impl.exchange_code(code)
    # exchange_code does NOT carry provider_user_id (the token payload has no
    # profile). Fetch it from the provider's basic-profile endpoint and stamp
    # it onto the tokens so upsert persists it server-side. fetch_profile is
    # best-effort: a None just leaves provider_user_id unset.
    fetch_profile = getattr(impl, "fetch_profile", None)
    if fetch_profile is not None and tokens.provider_user_id is None:
        uid = fetch_profile(tokens)
        if uid is not None:
            tokens.provider_user_id = uid
    store.upsert_provider_account(provider, tokens)
    # Immediate sync: the fresh account has no last_sync_at, so the sync
    # engine backfills whoop_backfill_days on this first pass.
    fitness_sync.tick()
    return RedirectResponse(_FITNESS_REDIRECT.format(provider=provider), status_code=302)


@router.post("/disconnect/{provider}", response_model=FitnessStatus)
def disconnect(provider: str) -> dict:
    """Revoke at the provider (best-effort), then delete its tokens + synced
    data. Manual workouts are preserved (the store keeps source != provider).
    Deletion is the user-facing guarantee, so a failed revoke never blocks it."""
    impl = providers.get(provider)
    tokens = store.get_provider_tokens(provider)
    if impl is not None and tokens is not None:
        try:
            impl.revoke(tokens)
        except Exception as exc:  # noqa: BLE001 — revoke is best-effort
            logger.warning("revoke failed for %s, deleting anyway: %s", provider, exc)
    if not store.delete_provider_data(provider):
        raise HTTPException(status_code=404, detail=f"No connected '{provider}' account")
    accounts = store.list_provider_accounts()
    return {
        "connected": any(a["status"] == "connected" for a in accounts),
        "providers": accounts,
    }
