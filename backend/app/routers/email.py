"""Email API (M5): the triaged inbox, one message with its live body, and sync.

Reads serve the normalized `emails` table only — the list is never a live Gmail
call (privacy: bodies are not persisted). The reading pane is the sole place a
body is fetched, on demand via EmailProvider.get_message, with a graceful
fallback string when Gmail is unreachable. Connect/disconnect/status live on
the shared /api/oauth/* router, not here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response

from .. import email_sync, providers
from ..schemas import EmailDetail, Inbox
from ..store import store

router = APIRouter(prefix="/api/email", tags=["email"])

logger = logging.getLogger("scuffed_os.email")

# Shown in the reading pane when the live Gmail body fetch fails — the row's
# metadata + AI summary still render, so the pane is never blank.
_BODY_UNAVAILABLE = "Message body is unavailable right now."


@router.get("/inbox", response_model=Inbox)
def inbox() -> dict:
    """The triaged inbox: needs_reply / fyi / untriaged groups + counts. Served
    from the emails table (never a live provider call)."""
    return store.inbox()


@router.get("/{email_id}", response_model=EmailDetail)
def email_detail(email_id: int) -> dict:
    """One message: stored metadata + AI summary, plus the full body fetched
    live from Gmail on demand. A failed fetch degrades to a fallback string so
    the pane still shows the sender/subject/summary."""
    row = store.get_email(email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    body = _BODY_UNAVAILABLE
    impl = providers.get(row["source"])
    get_message = getattr(impl, "get_message", None)
    if get_message is not None:
        try:
            body = get_message(row["source_id"])
        except Exception as exc:  # noqa: BLE001 — body fetch is best-effort
            logger.warning("body fetch failed for email %s: %s", email_id, exc)
    return {**row, "body": body}


@router.post("/sync")
def sync_now() -> dict:
    """Run one email sync pass now (manual/test/assistant). Delegates to
    email_sync.tick(); reads never depend on it, so a failing tick returns 0.
    `providers` lists the email providers that were polled."""
    count = email_sync.tick()
    try:
        names = [p.name for p in providers.all_providers()
                 if hasattr(p, "fetch_messages")]
    except RuntimeError:
        names = []
    return {"synced": count, "providers": names}


@router.post("/{email_id}/trash", status_code=204)
def trash_email(email_id: int) -> Response:
    """Trash in Gmail first; the local row is removed ONLY on success
    (confirm-first — a Gmail failure leaves the row untouched)."""
    row = store.get_email(email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    impl = providers.get(row["source"])
    trash_message = getattr(impl, "trash_message", None)
    if trash_message is None:
        raise HTTPException(status_code=502, detail="Gmail rejected the action")
    try:
        trash_message(row["source_id"])
    except Exception as exc:  # noqa: BLE001 — any provider failure is a 502, never a local change
        logger.warning("trash failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
    store.delete_email(email_id)
    return Response(status_code=204)
