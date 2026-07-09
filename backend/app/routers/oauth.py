"""Shared OAuth router (M5, callback reworked M9) — provider-registry-driven
connect/callback/disconnect/status, extracted from routers/fitness.py so a
second OAuth domain (email) reuses the plumbing. Domain-specific behavior lives
behind the OAuthProvider hooks: on_connected (kick the domain sync),
on_disconnect (delete the domain's data). The callback renders inline
success/error HTML (the backend serves no SPA); tokens never leave the server.

Two routers are exported: `router` under /api/oauth, and `auth_router` with NO
prefix so a provider-registered redirect lands at exactly /auth/{provider}/
callback (outside /api). main.py includes both.
"""
from __future__ import annotations

import html as _html
import logging
import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from .. import providers
from ..schemas import ConnectUrl, OAuthStatus
from ..store import store

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
    """Pop a state, returning the provider it was issued for (one-time use)."""
    return _STATES.pop(state, None)


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


def _callback_page(title: str, message: str, *, status_code: int) -> HTMLResponse:
    # Inline styles only (no <style> block) so there are no CSS braces to escape;
    # title/message are server-built and any reflected query value is escaped by
    # the caller.
    body = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title></head>"
        "<body style=\"font-family:-apple-system,system-ui,sans-serif;display:flex;"
        "min-height:100vh;margin:0;align-items:center;justify-content:center;background:#faf9f7\">"
        "<main style=\"max-width:28rem;padding:2rem;text-align:center;color:#1c1a17\">"
        f"<h1 style=\"font-size:1.25rem;margin:0 0 .5rem\">{title}</h1>"
        f"<p style=\"margin:0;color:#57534e;line-height:1.5\">{message}</p>"
        "</main></body></html>"
    )
    return HTMLResponse(content=body, status_code=status_code)


def _callback_success() -> HTMLResponse:
    return _callback_page(
        "✓ Connected",
        "You can close this tab and return to ScuffedOS.",
        status_code=200,
    )


def _callback_error(reason: str) -> HTMLResponse:
    return _callback_page(
        "Sign-in didn’t finish",
        f"{reason} Start again from Settings › Connectors.",
        status_code=400,
    )


@auth_router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str | None = None,
    error: str | None = None,
    state: str = Query(...),
) -> HTMLResponse:
    """OAuth redirect target (outside /api). Consume the one-time CSRF state on
    EVERY path, then either exchange the code (success) or render an inline
    error page. The backend serves no SPA, so there is no redirect back into the
    app — the user closes the tab and the Connectors tab's poll (Slice 2) picks
    up the flip. Tokens never leave the server."""
    issued_for = _consume_state(state)
    if issued_for is None or issued_for != provider:
        return _callback_error("This sign-in link has expired or is invalid.")
    if error is not None or code is None:
        detail = _html.escape(error) if error else "no authorization code was returned"
        return _callback_error(f"The provider reported: {detail}.")
    impl = providers.get(provider)
    if impl is None:
        return _callback_error(f"Unknown provider ‘{_html.escape(provider)}’.")
    try:
        tokens = impl.exchange_code(code)
        fetch_profile = getattr(impl, "fetch_profile", None)
        if fetch_profile is not None and tokens.provider_user_id is None:
            uid = fetch_profile(tokens)
            if uid is not None:
                tokens.provider_user_id = uid
        store.upsert_provider_account(provider, tokens)
    except Exception as exc:  # noqa: BLE001 — pre-persist failure surfaces as the error page
        logger.warning("oauth callback exchange failed for %s: %s", provider, exc)
        return _callback_error("The sign-in could not be completed.")
    # Account is now persisted (connected). A post-connect sync-hook failure must
    # NOT flip a successful connect into an error page — log and continue.
    try:
        impl.on_connected()   # immediate domain sync/backfill (fresh account → backfill)
    except Exception as exc:  # noqa: BLE001
        logger.warning("on_connected hook failed for %s (account already connected): %s", provider, exc)
    return _callback_success()


@router.post("/disconnect/{provider}", response_model=OAuthStatus)
def disconnect(provider: str) -> dict:
    """Revoke at the provider (best-effort), delete its tokens (+ any fitness
    data via delete_provider_data), then run the provider's on_disconnect hook
    to clear its domain data. Deletion is the user-facing guarantee, so a
    failed revoke never blocks it. A missing account → 404."""
    impl = providers.get(provider)
    # Guard: if the provider is unregistered, we cannot call on_disconnect to
    # clean its domain data, so refuse rather than orphaning data silently.
    if impl is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    tokens = store.get_provider_tokens(provider)
    if tokens is not None:
        try:
            impl.revoke(tokens)
        except Exception as exc:  # noqa: BLE001 — revoke is best-effort
            logger.warning("revoke failed for %s, deleting anyway: %s", provider, exc)
    # delete_provider_data removes the account row (+ fitness tables where
    # source==provider); its return value drives the 404 when no row exists.
    if not store.delete_provider_data(provider):
        raise HTTPException(status_code=404, detail=f"No connected '{provider}' account")
    # on_disconnect clears the provider's domain data. For WHOOP this re-calls
    # delete_provider_data (idempotent — row already gone); for Google it
    # deletes the emails table. Best-effort so a hook error never 500s the
    # user-facing delete.
    try:
        impl.on_disconnect()
    except Exception as exc:  # noqa: BLE001
        logger.warning("on_disconnect hook failed for %s: %s", provider, exc)
    return _status_dict()
