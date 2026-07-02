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
from ..providers.google import _build_rfc822
from ..schemas import (
    EmailDetail,
    EmailOut,
    FlagsPatch,
    ForwardEmail,
    Inbox,
    LabelOut,
    LabelsPatch,
    ReplyEmail,
    SendEmail,
)
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


@router.get("/labels", response_model=list[LabelOut])
def list_labels() -> list[dict]:
    """The label menu's options, straight from Gmail (no local labels table)."""
    impl = providers.get("google")
    list_labels_fn = getattr(impl, "list_labels", None)
    if list_labels_fn is None:
        raise HTTPException(status_code=502, detail="Gmail rejected the action")
    try:
        return list_labels_fn()
    except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
        logger.warning("list_labels failed: %s", exc)
        raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc


@router.post("/send")
def send_email(payload: SendEmail) -> dict:
    """Compose-new send. No local row is touched — sends are confirmed
    straight through to Gmail; the Sent-folder truth lives in Gmail itself."""
    impl = providers.get("google")
    send_message = getattr(impl, "send_message", None)
    if send_message is None:
        raise HTTPException(status_code=502, detail="Gmail rejected the action")
    raw = _build_rfc822(
        to=payload.to, cc=payload.cc, subject=payload.subject, body=payload.body,
    )
    try:
        new_id = send_message(raw)
    except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
        logger.warning("send failed: %s", exc)
        raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
    return {"id": new_id}


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


@router.post("/{email_id}/flags", response_model=EmailOut)
def set_email_flags(email_id: int, patch: FlagsPatch) -> dict:
    """Read/unread + star. unread=True -> add Gmail's UNREAD label;
    unread=False -> remove UNREAD. starred=True -> add STARRED;
    starred=False -> remove STARRED. Both None (an empty patch) is a no-op
    that skips the Gmail call entirely and returns the row unchanged."""
    row = store.get_email(email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    add: list[str] = []
    remove: list[str] = []
    if patch.unread is True:
        add.append("UNREAD")
    elif patch.unread is False:
        remove.append("UNREAD")
    if patch.starred is True:
        add.append("STARRED")
    elif patch.starred is False:
        remove.append("STARRED")
    if add or remove:
        impl = providers.get(row["source"])
        modify_labels = getattr(impl, "modify_labels", None)
        if modify_labels is None:
            raise HTTPException(status_code=502, detail="Gmail rejected the action")
        try:
            modify_labels(row["source_id"], add=add, remove=remove)
        except Exception as exc:  # noqa: BLE001 — any provider failure is a 502, never a local change
            logger.warning("flags update failed for email %s: %s", email_id, exc)
            raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
    updated = store.set_email_flags(email_id, unread=patch.unread, starred=patch.starred)
    return updated


@router.post("/{email_id}/labels", response_model=EmailOut)
def set_email_labels(email_id: int, patch: LabelsPatch) -> dict:
    """New label list = (stored ∪ add) − remove, confirmed against Gmail
    first via modify_labels, then written locally via store.set_email_labels
    (which also re-derives unread/starred from the new list)."""
    row = store.get_email(email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    impl = providers.get(row["source"])
    modify_labels = getattr(impl, "modify_labels", None)
    if modify_labels is None:
        raise HTTPException(status_code=502, detail="Gmail rejected the action")
    try:
        modify_labels(row["source_id"], add=patch.add, remove=patch.remove)
    except Exception as exc:  # noqa: BLE001 — any provider failure is a 502, never a local change
        logger.warning("labels update failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
    current = set(row.get("label_ids") or [])
    new_labels = list((current | set(patch.add)) - set(patch.remove))
    updated = store.set_email_labels(email_id, new_labels)
    return updated


def _prefixed(subject: str, prefix: str) -> str:
    """Add `prefix` (e.g. 'Re: ') unless subject already starts with it,
    case-insensitively (contract: no double-Re/double-Fwd)."""
    if subject.lower().startswith(prefix.lower()):
        return subject
    return f"{prefix}{subject}"


@router.post("/{email_id}/reply")
def reply_email(email_id: int, payload: ReplyEmail) -> dict:
    """Reply threads on the original: In-Reply-To/References from Gmail's
    live message-meta, thread_id from the stored row, subject 'Re: <orig>'
    (no double-Re), to = the original sender. No local row changes — Gmail's
    Sent folder is the source of truth for outbound mail."""
    original = store.get_email(email_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Email not found")
    impl = providers.get(original["source"])
    send_message = getattr(impl, "send_message", None)
    get_message_meta = getattr(impl, "get_message_meta", None)
    if send_message is None or get_message_meta is None:
        raise HTTPException(status_code=502, detail="Gmail rejected the action")
    try:
        meta = get_message_meta(original["source_id"])
        subject = _prefixed(meta["subject"] or original["subject"], "Re: ")
        references = f"{meta['references']} {meta['message_id']}".strip()
        raw = _build_rfc822(
            to=meta["from_email"], subject=subject, body=payload.body,
            in_reply_to=meta["message_id"], references=references,
        )
        new_id = send_message(raw, thread_id=original["thread_id"])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
        logger.warning("reply failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
    return {"id": new_id}


@router.post("/{email_id}/forward")
def forward_email(email_id: int, payload: ForwardEmail) -> dict:
    """Forward carries no threading headers (a fresh conversation for the new
    recipient) and always prefixes 'Fwd: ' (no double-Fwd). To comes from the
    payload, not the original sender."""
    original = store.get_email(email_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Email not found")
    impl = providers.get(original["source"])
    send_message = getattr(impl, "send_message", None)
    get_message_meta = getattr(impl, "get_message_meta", None)
    if send_message is None or get_message_meta is None:
        raise HTTPException(status_code=502, detail="Gmail rejected the action")
    try:
        meta = get_message_meta(original["source_id"])
        subject = _prefixed(meta["subject"] or original["subject"], "Fwd: ")
        raw = _build_rfc822(to=payload.to, subject=subject, body=payload.body)
        new_id = send_message(raw)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
        logger.warning("forward failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail="Gmail rejected the action") from exc
    return {"id": new_id}
