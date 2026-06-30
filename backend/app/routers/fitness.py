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

import secrets

from fastapi import APIRouter, HTTPException

from .. import providers
from ..schemas import ConnectUrl, FitnessStatus
from ..store import store

router = APIRouter(prefix="/api/fitness", tags=["fitness"])
auth_router = APIRouter(tags=["fitness-oauth"])

# One-time CSRF states: state token -> provider name. In-process is fine for
# a single-user desktop app (the spec's "stored server-side, one-time CSRF
# check"); a process restart mid-flow just makes the user click Connect again.
_STATES: dict[str, str] = {}


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
