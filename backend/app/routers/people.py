"""People CRUD + macOS Contacts consent lifecycle (M10 s1).

Structured contact fields (names, phones, emails, org/title, handle index) are
persisted to the configured PostgreSQL database (which may run locally or on a
remote/self-hosted server). Imported (source='macos_contacts') identity is
read-only through this API — edit it in Apple Contacts; only the ScuffedOS-owned
CRM-native fields are writable on an imported row. Extracted photos live on the
backend host's filesystem and are served by relative key with a containment
check (see providers/contact_photos.py, Task 5)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse

from .. import contacts_sync
from ..config import settings
from ..providers import contact_photos
from ..schemas import (
    ContactsEnableIn, ContactsForgetIn, ContactsStateOut, PeoplePage,
    PersonCreate, PersonOut, PersonUpdate, SyncResultOut,
)
from ..store import store

router = APIRouter(prefix="/api/people", tags=["people"])

# Sync-owned identity fields; on a non-manual row these are read-only via the API.
_IDENTITY_FIELDS = {
    "display_name", "first_name", "last_name", "nickname",
    "organization", "job_title", "phones", "emails",
}


@router.get("", response_model=PeoplePage)
def list_people(
    q: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return store.list_people(q=q, cursor=cursor, limit=limit)   # Task 3's list (single owner)


@router.get("/{person_id}", response_model=PersonOut)
def get_person(person_id: int) -> dict:
    person = store.get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


@router.post("", response_model=PersonOut, status_code=201)
def create_person(body: PersonCreate) -> dict:
    try:
        return store.create_person(body.model_dump())
    except ValueError as exc:   # whitespace-only display_name
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/{person_id}", response_model=PersonOut)
def update_person(person_id: int, body: PersonUpdate) -> dict:
    existing = store.get_person(person_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Person not found")
    patch = body.model_dump(exclude_unset=True)
    if existing["source"] != "manual" and (_IDENTITY_FIELDS & patch.keys()):
        raise HTTPException(
            status_code=409,
            detail="Imported contact identity is read-only; edit it in Apple Contacts.",
        )
    updated = store.update_person(person_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return updated


@router.delete("/{person_id}", status_code=204)
def delete_person(person_id: int) -> Response:
    existing = store.get_person(person_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if existing["source"] != "manual":
        raise HTTPException(
            status_code=409,
            detail="Imported contacts can't be deleted individually; use Disconnect or Forget.",
        )
    store.delete_person(person_id)
    return Response(status_code=204)


# ---- macOS Contacts consent lifecycle -------------------------------------
@router.post("/contacts/enable", response_model=ContactsStateOut)
def enable_contacts(body: ContactsEnableIn) -> dict:
    if not body.ack_storage_disclosure:
        raise HTTPException(
            status_code=400,
            detail="Acknowledge the storage disclosure before enabling Contacts.",
        )
    store.enable_contacts(region=settings.contacts_default_region)
    contacts_sync.tick()   # first-sync kick; failures land in state, never raised
    return store.get_contacts_state()


@router.post("/contacts/disconnect", response_model=ContactsStateOut)
def disconnect_contacts() -> dict:
    return store.disconnect_contacts()


@router.post("/contacts/forget", response_model=ContactsStateOut)
def forget_contacts(body: ContactsForgetIn) -> dict:
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Forgetting imported Contacts is destructive; resend with confirm=true.",
        )
    return store.forget_contacts()


@router.post("/sync", response_model=SyncResultOut)
def sync_now() -> SyncResultOut:
    """Run one contacts sync pass now (manual). Reads never depend on it. Returns a
    SyncResult; a no-op 'disabled' when consent is off; 'error' if the database is
    unreachable."""
    result = contacts_sync.tick()
    return SyncResultOut(
        status=result.status, access=result.access, imported=result.imported,
        updated=result.updated, removed=result.removed,
        last_sync_at=result.last_sync_at, last_error=result.last_error,
    )


@router.get("/{person_id}/photo")
def get_person_photo(person_id: int) -> FileResponse:
    """Serve a contact photo by containment-checked relative key. Defensively
    wraps contact_photos.resolve_photo — a malformed/null-byte key can make its
    os.path.realpath call raise rather than return None, and that must 404 (not
    500) just like every other unresolvable-photo case."""
    key = store.get_person_photo_key(person_id)
    if not key:
        raise HTTPException(status_code=404, detail="No photo")
    root = settings.contacts_photos_root()
    try:
        target = contact_photos.resolve_photo(key, root)
    except Exception:
        target = None
    if target is None:
        raise HTTPException(status_code=404, detail="No photo")
    try:
        with open(target, "rb") as fh:
            head = fh.read(16)
    except OSError:
        raise HTTPException(status_code=404, detail="No photo")
    detected = contact_photos.detect_media_type(head)
    if detected is None:
        raise HTTPException(status_code=404, detail="No photo")
    _ext, media_type = detected
    return FileResponse(target, media_type=media_type)
