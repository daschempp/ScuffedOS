# People/CRM + macOS Contacts Sync — Implementation Plan (Messaging M10, Slice 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real, DB-backed People/CRM and populate it one-way from the local macOS Contacts (AddressBook) database, establishing the Full Disk Access flow and a `resolve_handle()` seam the iMessage slice will consume.

**Architecture:** Mirror the existing "synced-connector" recipe (Email/Moodle): a `Person` table keyed `(owner, source, source_id)` upserted idempotently, a pure local reader (`providers/macos_contacts.py`) instead of a network provider, a token-less `contacts_sync.py` engine, a CRUD `routers/people.py`, and a fifth Connectors card with a new `auth_kind="local"` whose "connectedness" is a Full-Disk-Access probe. Handle→person resolution is backed by a `person_handle` index table. Everything stays on-device.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, Postgres/pgvector (SQLite in tests), `phonenumberslite` (new), Vite/React (JS).

## Global Constraints

- **Target platform:** macOS 26.x (schema historically stable at `AddressBook-v22`; read defensively — probe columns, never hardcode entity numbers).
- **Python:** 3.14 (`locale.getlocale()`, never the deprecated `getdefaultlocale()`).
- **New dependency:** `phonenumberslite` (pure-Python, offline, vendored via `scripts/vendor-python.sh`). NOT the full `phonenumbers`.
- **Alembic head is `0009`;** this slice adds exactly one migration, `0010_people.py` (`down_revision="0009"`).
- **All-local, zero network egress** in this slice. Contact data lives only in the app DB + `contacts_photos_dir`.
- **One-way import:** never write to the AddressBook DB (open `file:...?mode=ro&immutable=1`). Sync writes only *sync-owned* fields; **CRM-native fields (`relationship`, `relationship_strength`, `notes`, `pinned`, `last_contacted_at`) are never touched by sync.**
- **Feature-absent sync-abort:** a *failed/denied* read raises `ContactsAccessError`; the sync must **not** run soft-deletion reconciliation on a failed read (only on a genuinely-empty successful read), or it would soft-delete every contact.
- **FDA detection:** attempt an actual read and catch `PermissionError` errno 1 (EPERM); never trust `os.access()`.
- **Governing principle (future slices):** no auto-send, ever — every outbound message requires explicit per-message user approval. (Not implemented here; recorded so it is not designed away.)
- **Per-repo rules:** TDD (failing test first); after each task run the FULL backend suite (`cd backend && pytest -q`) and report the pass count (baseline ≈ 699); function-local `from .config import settings` inside store methods; stamp `owner=settings.owner` on every row; frequent commits.

---

## File Structure

**Create:**
- `backend/app/identity.py` — phone/email canonicalization (pure).
- `backend/app/providers/macos_contacts.py` — local AddressBook reader + FDA probe (pure, injectable path).
- `backend/app/contacts_sync.py` — token-less sync engine.
- `backend/app/routers/people.py` — People CRUD + `/sync` + `/photo`.
- `backend/alembic/versions/0010_people.py` — `people` + `person_handle` tables.
- Tests: `backend/tests/test_identity.py`, `test_macos_contacts_reader.py`, `test_macos_contacts_photos.py`, `test_people_store.py`, `test_contacts_sync.py`, `test_people_api.py`, and additions to `test_connectors.py`.
- `docs/people.md`.

**Modify:**
- `backend/app/models.py` — `Person`, `PersonHandle` models.
- `backend/app/providers/base.py` — `NormalizedPerson` dataclass.
- `backend/app/store.py` — field-map + person methods.
- `backend/app/config.py` — `_default_region()` + contacts settings + `contacts_photos_dir`.
- `backend/app/main.py` — import + lifespan wiring + router include.
- `backend/app/routers/connectors.py` — `macos_contacts` catalog + FDA probe + `_contacts_connector()`.
- `backend/app/schemas.py` — `PersonOut/Create/Update`; widen `ConnectorInfo` Literals + `access`.
- `backend/requirements.txt` — add `phonenumberslite`.
- `frontend/src/lib/api.js` — People methods.
- `frontend/src/screens/CRMScreen.jsx` — real data.
- `frontend/src/screens/ConnectorsPanel.jsx` — `local` branch card.
- `docs/privacy-policy.md`, `README.md`.

---

## Task 1: Identity canonicalization (`identity.py`)

Pure module, no macOS, no DB. Foundation for handle indexing + resolution.

**Files:**
- Create: `backend/app/identity.py`
- Create: `backend/tests/test_identity.py`
- Modify: `backend/requirements.txt` (add `phonenumberslite`)

**Interfaces:**
- Produces: `canon_email(raw: str) -> str`; `canon_phone(raw: str, default_region: str) -> dict | None`; `canon_handle(raw: str, default_region: str) -> dict | None`. The dict shape is `{"normalized": str, "kind": "phone"|"email"|"short", "possible": bool}`.

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:
```
phonenumberslite
```
Then install into the dev venv: `cd backend && ../.venv/bin/python -m pip install phonenumberslite`

- [ ] **Step 2: Write the failing test** — `backend/tests/test_identity.py`

```python
from app.identity import canon_email, canon_phone, canon_handle


def test_phone_variants_collapse_to_one_e164_key():
    for raw in ["+15551234567", "5551234567", "(555) 123-4567", "1-555-123-4567", "555.123.4567"]:
        assert canon_phone(raw, "US")["normalized"] == "+15551234567"


def test_phone_keyed_even_when_not_valid():
    # 555 test range: possible but not "valid" — we must still key it, not drop it.
    r = canon_phone("5551234567", "US")
    assert r["normalized"] == "+15551234567"
    assert r["kind"] == "phone"


def test_wrong_region_is_not_us_forced():
    # A UK national number parsed with the UK region canonicalizes correctly.
    assert canon_phone("020 8366 1177", "GB")["normalized"] == "+442083661177"


def test_short_code():
    r = canon_phone("611", "US")
    assert r["kind"] == "short"
    assert r["normalized"] == "short:611"


def test_unparseable_phone_falls_back_to_digits():
    r = canon_phone("not a phone", "US")
    assert r is None or r["kind"] == "phone"
    assert canon_phone("", "US") is None


def test_email_lowercased_nfc_no_dot_folding():
    assert canon_email("Foo@iCloud.com") == "foo@icloud.com"
    # dots are significant everywhere except gmail — do NOT strip them
    assert canon_email("f.o.o@icloud.com") == "f.o.o@icloud.com"


def test_canon_handle_dispatch():
    assert canon_handle("foo@icloud.com", "US")["kind"] == "email"
    assert canon_handle("+15551234567", "US")["kind"] == "phone"
    assert canon_handle("", "US") is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_identity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.identity'`

- [ ] **Step 4: Write the implementation** — `backend/app/identity.py`

```python
"""Canonicalize phone numbers and emails to a stable key for identity matching.

A single handle ("+15551234567", "5551234567", "Foo@iCloud.com") must collapse
to one key so an inbound message handle resolves to the right contact. Phones go
to E.164 via phonenumberslite (pure-Python, offline); the key is stored
REGARDLESS of validity (gating on is_valid_number drops legitimate test/MVNO
ranges). Emails are NFC + trim + lowercase — no Gmail dot/plus folding (that is
a gmail.com-only rule and false-merges iCloud/custom domains).
"""
from __future__ import annotations

import re
import unicodedata

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, shortnumberinfo


def canon_email(raw: str) -> str:
    return unicodedata.normalize("NFC", raw or "").strip().lower()


def canon_phone(raw: str, default_region: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        n = phonenumbers.parse(raw, default_region)
    except NumberParseException:
        digits = re.sub(r"\D", "", raw)
        return {"normalized": digits, "kind": "phone", "possible": False} if digits else None
    if shortnumberinfo.is_valid_short_number(n):
        return {"normalized": f"short:{n.national_number}", "kind": "short", "possible": False}
    e164 = phonenumbers.format_number(n, PhoneNumberFormat.E164)
    return {"normalized": e164, "kind": "phone", "possible": phonenumbers.is_possible_number(n)}


def canon_handle(raw: str, default_region: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if "@" in raw:
        value = canon_email(raw)
        return {"normalized": value, "kind": "email", "possible": True} if value else None
    return canon_phone(raw, default_region)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_identity.py -q`
Expected: PASS (all 7)

- [ ] **Step 6: Run the full suite + commit**

Run: `cd backend && pytest -q` (report the count)
```bash
git add backend/app/identity.py backend/tests/test_identity.py backend/requirements.txt
git commit -m "feat(people): phone/email canonicalization via phonenumberslite (M10 s1)"
```

---

## Task 2: `Person` + `PersonHandle` models + `0010` migration

**Files:**
- Modify: `backend/app/models.py` (append after the last class)
- Create: `backend/alembic/versions/0010_people.py`
- Create: `backend/tests/test_migrations_people.py` (or extend `tests/test_migrations.py`)

**Interfaces:**
- Produces: ORM `Person` (table `people`) and `PersonHandle` (table `person_handle`) on `Base.metadata`, with the exact columns Task 3 reads/writes.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_migrations_people.py`

```python
from sqlalchemy import create_engine, inspect

from app.db import Base
import app.models  # noqa: F401  — register tables


def test_people_and_person_handle_tables_exist_on_metadata():
    names = set(Base.metadata.tables)
    assert "people" in names
    assert "person_handle" in names


def test_people_columns():
    cols = {c.name for c in Base.metadata.tables["people"].columns}
    assert {"owner", "source", "source_id", "display_name", "phones", "emails",
            "photo_path", "has_photo", "relationship", "relationship_strength",
            "notes", "pinned", "last_contacted_at", "removed_from_source_at"} <= cols


def test_create_all_builds_both_tables_on_sqlite():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    tables = set(inspect(eng).get_table_names())
    assert {"people", "person_handle"} <= tables
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_migrations_people.py -q`
Expected: FAIL — `'people' not in names`

- [ ] **Step 3: Add the ORM models** — append to `backend/app/models.py` (after the final class; `ForeignKey`, `String`, `Text`, `DateTime`, `JSONField`, `utcnow`, `Mapped`, `mapped_column` are already imported)

```python
class Person(Base):
    """A contact (M10). source='macos_contacts' rows are synced one-way from the
    local AddressBook and keyed (owner, source, source_id) for idempotent upsert;
    source='manual' rows are user-created. Sync writes only the sync-owned fields;
    the CRM-native fields (relationship..last_contacted_at) are ScuffedOS-owned and
    never touched by sync. removed_from_source_at soft-deletes a contact that
    vanished from AddressBook (preserving CRM data), cleared on any re-upsert."""

    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_people_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'macos_contacts' | 'manual'
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(Text, default="")
    first_name: Mapped[str] = mapped_column(Text, default="")
    last_name: Mapped[str] = mapped_column(Text, default="")
    nickname: Mapped[str] = mapped_column(Text, default="")
    organization: Mapped[str] = mapped_column(Text, default="")
    job_title: Mapped[str] = mapped_column(Text, default="")
    phones: Mapped[list] = mapped_column(JSONField, default=list)      # [{value,label,normalized}]
    emails: Mapped[list] = mapped_column(JSONField, default=list)      # [{value,label,normalized}]
    photo_path: Mapped[str | None] = mapped_column(Text)
    has_photo: Mapped[bool] = mapped_column(default=False)
    # ---- CRM-native (ScuffedOS-owned; sync never writes these) ----
    relationship: Mapped[str | None] = mapped_column(String(32))
    relationship_strength: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(default=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_from_source_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PersonHandle(Base):
    """Normalized handle -> person index for resolve_handle (M10). One row per
    (person_id, kind, value); value is the canonical key from app.identity. Kept
    across soft-delete so historical messages still resolve to a removed contact."""

    __tablename__ = "person_handle"
    __table_args__ = (
        UniqueConstraint("person_id", "kind", "value",
                         name="uq_person_handle_person_kind_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))       # 'phone' | 'email' | 'short'
    value: Mapped[str] = mapped_column(String(320), index=True)  # normalized key
    possible: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

- [ ] **Step 4: Write the migration** — `backend/alembic/versions/0010_people.py`

```python
"""People domain (M10 s1): local contacts directory + handle index.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("organization", sa.Text(), nullable=False),
        sa.Column("job_title", sa.Text(), nullable=False),
        sa.Column("phones", JSONField, nullable=False),
        sa.Column("emails", JSONField, nullable=False),
        sa.Column("photo_path", sa.Text(), nullable=True),
        sa.Column("has_photo", sa.Boolean(), nullable=False),
        sa.Column("relationship", sa.String(length=32), nullable=True),
        sa.Column("relationship_strength", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_from_source_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_people_owner_source_source_id"),
    )
    op.create_index(op.f("ix_people_owner"), "people", ["owner"])
    op.create_index(op.f("ix_people_source"), "people", ["source"])
    op.create_index(op.f("ix_people_source_id"), "people", ["source_id"])

    op.create_table(
        "person_handle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.Integer(),
                  sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=320), nullable=False),
        sa.Column("possible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("person_id", "kind", "value",
                            name="uq_person_handle_person_kind_value"),
    )
    op.create_index(op.f("ix_person_handle_owner"), "person_handle", ["owner"])
    op.create_index(op.f("ix_person_handle_person_id"), "person_handle", ["person_id"])
    op.create_index(op.f("ix_person_handle_value"), "person_handle", ["value"])


def downgrade() -> None:
    op.drop_table("person_handle")
    op.drop_table("people")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_migrations_people.py -q`
Expected: PASS (3)

- [ ] **Step 6: Verify the migration applies both directions** (needs dev Postgres; skip if unavailable and note it)

Run: `cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: no errors; head reports `0010`.

- [ ] **Step 7: Full suite + commit**

Run: `cd backend && pytest -q` (report count)
```bash
git add backend/app/models.py backend/alembic/versions/0010_people.py backend/tests/test_migrations_people.py
git commit -m "feat(people): Person + PersonHandle models + 0010 migration (M10 s1)"
```

---

## Task 3: Store methods (`NormalizedPerson`, upsert, handle index, CRUD, resolve, reconcile)

**Files:**
- Modify: `backend/app/providers/base.py` (add `NormalizedPerson`)
- Modify: `backend/app/store.py` (field-map, imports, person methods)
- Create: `backend/tests/test_people_store.py`

**Interfaces:**
- Consumes: `Person`, `PersonHandle` (Task 2); `canon_handle` (Task 1); `settings.contacts_default_region` (Task 5 adds it — for tests, `store` tests can pass region via the reader; `upsert_person` reads it from settings, default provided in Task 5. To keep Task 3 self-contained, add the settings field here if Task 5 not yet done — see Step 1 note).
- Produces:
  - `NormalizedPerson(source, source_id, display_name, first_name="", last_name="", nickname="", organization="", job_title="", phones=[], emails=[], photo_path=None, has_photo=False, meta={})` — `phones`/`emails` are `[{value,label}]` (reader) OR `[{value,label,normalized}]`; `upsert_person` fills `normalized`.
  - `store.upsert_person(person: NormalizedPerson) -> dict`
  - `store.list_people(include_removed: bool = False) -> list[dict]`
  - `store.get_person(person_id: int) -> dict | None`
  - `store.create_person(data: dict) -> dict`
  - `store.update_person(person_id: int, patch: dict) -> dict | None`
  - `store.delete_person(person_id: int) -> bool`
  - `store.resolve_handle(handle: str) -> list[dict]`
  - `store.reconcile_people(source: str, seen_source_ids: list[str], now: datetime) -> int`
  - module `_person_dict(p: Person) -> dict`

- [ ] **Step 1: Add `NormalizedPerson`** — `backend/app/providers/base.py` (near `NormalizedEmail`)

```python
@dataclass
class NormalizedPerson:
    source: str
    source_id: str
    display_name: str
    first_name: str = ""
    last_name: str = ""
    nickname: str = ""
    organization: str = ""
    job_title: str = ""
    phones: list = field(default_factory=list)   # [{value, label}] — normalized filled by the store
    emails: list = field(default_factory=list)   # [{value, label}]
    photo_path: str | None = None
    has_photo: bool = False
    meta: dict = field(default_factory=dict)
```

> Note: `store.upsert_person` reads `settings.contacts_default_region`. If Task 5 hasn't run yet, add `contacts_default_region: str = "US"` to `config.py` now (Task 5 upgrades the default to `_default_region()`), so this task's tests run.

- [ ] **Step 2: Write the failing test** — `backend/tests/test_people_store.py`

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.providers.base import NormalizedPerson
from app.store import store


@pytest.fixture(autouse=True)
def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    store.configure(sessionmaker(eng))
    yield
    store.configure(None)


def _np(**kw):
    kw.setdefault("source", "macos_contacts")
    kw.setdefault("display_name", "Jane Doe")
    return NormalizedPerson(**kw)


def test_upsert_is_idempotent_and_indexes_handles():
    store.upsert_person(_np(source_id="A", phones=[{"value": "(555) 123-4567", "label": "Mobile"}],
                            emails=[{"value": "Jane@iCloud.com", "label": "Home"}]))
    again = store.upsert_person(_np(source_id="A", display_name="Jane D."))
    people = store.list_people()
    assert len(people) == 1               # updated in place, no dup
    assert people[0]["display_name"] == "Jane D."
    # handle index normalized both a phone and an email
    hits = store.resolve_handle("+15551234567")
    assert [p["id"] for p in hits] == [again["id"]]
    assert store.resolve_handle("jane@icloud.com")[0]["id"] == again["id"]


def test_resolve_handle_returns_all_matches_for_shared_handle():
    a = store.upsert_person(_np(source_id="A", display_name="Sue",
                                phones=[{"value": "+15550001111", "label": "Home"}]))
    b = store.upsert_person(_np(source_id="B", display_name="Bob",
                                phones=[{"value": "+15550001111", "label": "Home"}]))
    ids = {p["id"] for p in store.resolve_handle("+15550001111")}
    assert ids == {a["id"], b["id"]}


def test_sync_never_clobbers_crm_native_fields():
    p = store.upsert_person(_np(source_id="A"))
    store.update_person(p["id"], {"relationship": "Family", "notes": "college roommate", "pinned": True})
    store.upsert_person(_np(source_id="A", display_name="Jane Renamed"))  # a re-sync
    got = store.get_person(p["id"])
    assert got["display_name"] == "Jane Renamed"   # sync-owned updated
    assert got["relationship"] == "Family"          # CRM-native preserved
    assert got["notes"] == "college roommate"
    assert got["pinned"] is True


def test_reconcile_soft_deletes_missing_and_resurrect_on_return():
    store.upsert_person(_np(source_id="A"))
    store.upsert_person(_np(source_id="B"))
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    flipped = store.reconcile_people("macos_contacts", seen_source_ids=["A"], now=now)
    assert flipped == 1
    assert len(store.list_people()) == 1                     # B hidden
    assert len(store.list_people(include_removed=True)) == 2
    store.upsert_person(_np(source_id="B"))                  # B returns
    assert len(store.list_people()) == 2                     # resurrected


def test_manual_crud():
    p = store.create_person({"display_name": "Manual Person",
                             "emails": [{"value": "m@x.com", "label": "Home"}]})
    assert p["source"] == "manual"
    assert store.get_person(p["id"])["display_name"] == "Manual Person"
    store.update_person(p["id"], {"display_name": "Renamed"})
    assert store.get_person(p["id"])["display_name"] == "Renamed"
    assert store.delete_person(p["id"]) is True
    assert store.get_person(p["id"]) is None
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && pytest tests/test_people_store.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'upsert_person'`

- [ ] **Step 4: Add the field-map + import** — in `store.py`

Add `Person, PersonHandle` to the `from .models import (...)` block. After `_EMAIL_FIELDS` (~line 65) add:
```python
_PERSON_SYNC_FIELDS = (
    "display_name", "first_name", "last_name", "nickname",
    "organization", "job_title", "photo_path", "has_photo",
)
```

- [ ] **Step 5: Add `_person_dict`** — module-level, near `_email_dict`

```python
def _person_dict(p: Person) -> dict:
    return {
        "id": p.id,
        "source": p.source,
        "source_id": p.source_id,
        "display_name": p.display_name,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "nickname": p.nickname,
        "organization": p.organization,
        "job_title": p.job_title,
        "phones": p.phones or [],
        "emails": p.emails or [],
        "has_photo": p.has_photo,
        "relationship": p.relationship,
        "relationship_strength": p.relationship_strength,
        "notes": p.notes,
        "pinned": p.pinned,
        "last_contacted_at": aware_utc(p.last_contacted_at),
        "removed_from_source_at": aware_utc(p.removed_from_source_at),
        "created_at": aware_utc(p.created_at),
        "updated_at": aware_utc(p.updated_at),
    }
```

- [ ] **Step 6: Add the person store methods** — in class `Store`, after `get_email` (add a `# ---- people (M10) ----` marker)

```python
    # ---- people (M10) ----
    def _person_row(self, s: Session, source: str, source_id: str) -> Person | None:
        from .config import settings

        return s.scalars(
            select(Person)
            .where(Person.owner == settings.owner)
            .where(Person.source == source)
            .where(Person.source_id == source_id)
        ).first()

    def _reindex_handles(self, s: Session, row: Person) -> None:
        """Rebuild a person's normalized handle rows from its phones/emails."""
        from .config import settings
        from .identity import canon_handle

        s.query(PersonHandle).filter(PersonHandle.person_id == row.id).delete()
        seen: set[tuple[str, str]] = set()
        for bucket in ((row.phones or []), (row.emails or [])):
            for entry in bucket:
                value = (entry or {}).get("value", "")
                canon = canon_handle(value, settings.contacts_default_region)
                if canon is None:
                    continue
                entry["normalized"] = canon["normalized"]
                key = (canon["kind"], canon["normalized"])
                if key in seen:
                    continue
                seen.add(key)
                s.add(PersonHandle(
                    owner=settings.owner, person_id=row.id,
                    kind=canon["kind"], value=canon["normalized"],
                    possible=canon["possible"],
                ))

    @_retry_integrity
    def upsert_person(self, person: NormalizedPerson) -> dict:
        """Get-or-create by (owner, 'macos_contacts', source_id). Writes only the
        sync-owned fields + phones/emails/meta; NEVER touches CRM-native fields.
        Clears removed_from_source_at so a returning contact is resurrected."""
        from .config import settings

        with self._session() as s, s.begin():
            row = self._person_row(s, person.source, person.source_id)
            if row is None:
                row = Person(owner=settings.owner, source=person.source,
                             source_id=person.source_id)
                s.add(row)
            for field in _PERSON_SYNC_FIELDS:
                setattr(row, field, getattr(person, field))
            row.phones = [dict(p) for p in person.phones]
            row.emails = [dict(e) for e in person.emails]
            row.meta = {**(row.meta or {}), **person.meta}
            row.removed_from_source_at = None
            s.flush()
            self._reindex_handles(s, row)
            s.flush()
            return _person_dict(row)

    def list_people(self, include_removed: bool = False) -> list[dict]:
        from .config import settings

        with self._session() as s:
            q = select(Person).where(Person.owner == settings.owner)
            if not include_removed:
                q = q.where(Person.removed_from_source_at.is_(None))
            rows = s.scalars(q.order_by(Person.display_name)).all()
            return [_person_dict(r) for r in rows]

    def get_person(self, person_id: int) -> dict | None:
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            return _person_dict(row) if row is not None else None

    @_retry_integrity
    def create_person(self, data: dict) -> dict:
        """Manual (source='manual') create. Writes any provided field incl.
        CRM-native; generates a source_id."""
        import uuid

        from .config import settings

        with self._session() as s, s.begin():
            row = Person(owner=settings.owner, source="manual",
                         source_id=uuid.uuid4().hex)
            for key, value in data.items():
                if hasattr(row, key) and key not in ("id", "owner", "source", "source_id"):
                    setattr(row, key, value)
            if not row.display_name:
                row.display_name = data.get("name", "")
            s.add(row)
            s.flush()
            self._reindex_handles(s, row)
            s.flush()
            return _person_dict(row)

    def update_person(self, person_id: int, patch: dict) -> dict | None:
        from .config import settings

        with self._session() as s, s.begin():
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            if row is None:
                return None
            for key, value in patch.items():
                if hasattr(row, key) and key not in ("id", "owner", "source", "source_id"):
                    setattr(row, key, value)
            s.flush()
            if "phones" in patch or "emails" in patch:
                self._reindex_handles(s, row)
                s.flush()
            return _person_dict(row)

    def delete_person(self, person_id: int) -> bool:
        from .config import settings

        with self._session() as s, s.begin():
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            if row is None:
                return False
            s.delete(row)  # person_handle rows cascade
            return True

    def resolve_handle(self, handle: str) -> list[dict]:
        """All People carrying this handle (shared handles -> multiple), ordered
        most-recently-contacted first. Includes soft-deleted people so historical
        messages still resolve. Empty list if none."""
        from .config import settings
        from .identity import canon_handle

        canon = canon_handle(handle, settings.contacts_default_region)
        if canon is None:
            return []
        with self._session() as s:
            rows = s.scalars(
                select(Person)
                .join(PersonHandle, PersonHandle.person_id == Person.id)
                .where(Person.owner == settings.owner)
                .where(PersonHandle.value == canon["normalized"])
                .order_by(Person.last_contacted_at.desc().nullslast(),
                          Person.updated_at.desc())
            ).all()
            return [_person_dict(r) for r in rows]

    @_retry_integrity
    def reconcile_people(self, source: str, seen_source_ids: list[str],
                         now: datetime) -> int:
        """Soft-delete synced people no longer present in the source snapshot.
        NEVER a hard delete. Caller must skip this on a FAILED read."""
        from .config import settings

        seen = set(seen_source_ids)
        flipped = 0
        with self._session() as s, s.begin():
            rows = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.source == source)
                .where(Person.removed_from_source_at.is_(None))
            ).all()
            for row in rows:
                if row.source_id not in seen:
                    row.removed_from_source_at = _to_utc(now)
                    flipped += 1
            return flipped
```

> `nullslast()` import: add `from sqlalchemy import nulls_last` is not needed — use `.desc().nullslast()` which is a column-expression method available in SQLAlchemy 2.0. If the installed version lacks it, replace the order_by with `.order_by(Person.updated_at.desc())`.

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_people_store.py -q`
Expected: PASS (5)

- [ ] **Step 8: Full suite + commit**

Run: `cd backend && pytest -q` (report count)
```bash
git add backend/app/store.py backend/app/providers/base.py backend/tests/test_people_store.py backend/app/config.py
git commit -m "feat(people): store upsert/CRUD/resolve_handle(list)/reconcile + handle index (M10 s1)"
```

---

## Task 4: macOS Contacts reader (`providers/macos_contacts.py`)

The novel, macOS-specific code. Pure + injectable path; a fixture `.abcddb` drives the tests so no real Mac files are touched.

**Files:**
- Create: `backend/app/providers/macos_contacts.py`
- Create: `backend/tests/conftest_addressbook.py` (fixture builder) or a fixture in the test files
- Create: `backend/tests/test_macos_contacts_reader.py`
- Create: `backend/tests/test_macos_contacts_photos.py`

**Interfaces:**
- Consumes: `NormalizedPerson` (Task 3), `canon_phone` (Task 1).
- Produces:
  - `class ContactsAccessError(Exception)` — raised when the store is unreadable (EPERM/denied).
  - `probe_access(root: str = DEFAULT_ROOT) -> str` → `"granted" | "denied" | "unknown"` (never raises).
  - `read_contacts(root: str = DEFAULT_ROOT, *, default_region: str, photos_dir: str | None = None) -> list[NormalizedPerson]` (raises `ContactsAccessError` on a failed read; returns `[]` on a genuinely empty store).
  - `DEFAULT_ROOT = "~/Library/Application Support/AddressBook"`.

- [ ] **Step 1: Write a fixture-DB builder + the failing reader test** — `backend/tests/test_macos_contacts_reader.py`

```python
import os
import sqlite3

import pytest

from app.providers.macos_contacts import (
    ContactsAccessError, probe_access, read_contacts,
)

# Entity number is discovered at runtime via Z_PRIMARYKEY, so we pick an
# arbitrary non-1 value here to prove the reader does NOT hardcode it.
_ENT_CONTACT = 19


def _build_store(db_path: str):
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);
        CREATE TABLE ZABCDRECORD (
            Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZUNIQUEID TEXT,
            ZFIRSTNAME TEXT, ZLASTNAME TEXT, ZNICKNAME TEXT,
            ZORGANIZATION TEXT, ZJOBTITLE TEXT, ZDISPLAYFLAGS INTEGER,
            ZTHUMBNAILIMAGEDATA BLOB
        );
        CREATE TABLE ZABCDPHONENUMBER (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZFULLNUMBER TEXT,
            ZLABEL TEXT, ZORDERINGINDEX INTEGER
        );
        CREATE TABLE ZABCDEMAILADDRESS (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZADDRESS TEXT,
            ZLABEL TEXT, ZORDERINGINDEX INTEGER
        );
        """
    )
    con.execute("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, 'ABCDContact')", (_ENT_CONTACT,))
    con.execute("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (20, 'ABCDGroup')")
    # a normal person
    con.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZDISPLAYFLAGS) "
        "VALUES (1, ?, 'UID-1:ABPerson', 'Jane', 'Doe', 0)", (_ENT_CONTACT,))
    con.execute("INSERT INTO ZABCDPHONENUMBER (Z_PK, ZOWNER, ZFULLNUMBER, ZLABEL, ZORDERINGINDEX) "
                "VALUES (1, 1, '(555) 123-4567', '_$!<Mobile>!$_', 0)")
    con.execute("INSERT INTO ZABCDEMAILADDRESS (Z_PK, ZOWNER, ZADDRESS, ZLABEL, ZORDERINGINDEX) "
                "VALUES (1, 1, 'Jane@iCloud.com', '_$!<Home>!$_', 0)")
    # a company row (ZDISPLAYFLAGS bit0)
    con.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZORGANIZATION, ZDISPLAYFLAGS) "
        "VALUES (2, ?, 'UID-2:ABPerson', 'Acme Inc', 1)", (_ENT_CONTACT,))
    # a NULL-displayflags row (must be treated as not-company, not crash)
    con.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS) "
        "VALUES (3, ?, 'UID-3:ABPerson', 'Solo', NULL)", (_ENT_CONTACT,))
    # a GROUP row that must be excluded
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZNICKNAME) "
                "VALUES (4, 20, 'UID-G:ABGroup', 'My Group')")
    con.commit()
    con.close()


@pytest.fixture
def ab_root(tmp_path):
    root = tmp_path / "AddressBook"
    root.mkdir()
    _build_store(str(root / "AddressBook-v22.abcddb"))
    src = root / "Sources" / "ABCDEF"
    src.mkdir(parents=True)
    # a second source with one more person, proving multi-source union
    con = sqlite3.connect(str(src / "AddressBook-v22.abcddb"))
    con.executescript(open(os.devnull).read() if False else "")  # noop
    _build_store(str(src / "AddressBook-v22.abcddb"))
    return str(root)


def test_reads_and_normalizes_people(ab_root):
    people = read_contacts(ab_root, default_region="US")
    janes = [p for p in people if p.first_name == "Jane"]
    assert janes, "Jane should be read from at least one store"
    jane = janes[0]
    assert jane.source == "macos_contacts"
    assert jane.source_id.endswith("UID-1:ABPerson")
    assert jane.phones[0]["value"] == "(555) 123-4567"
    assert jane.phones[0]["label"] == "Mobile"          # unwrapped
    assert jane.emails[0]["label"] == "Home"


def test_excludes_groups(ab_root):
    people = read_contacts(ab_root, default_region="US")
    assert all("ABGroup" not in p.source_id for p in people)


def test_company_and_null_displayflags(ab_root):
    people = read_contacts(ab_root, default_region="US")
    acme = next(p for p in people if p.organization == "Acme Inc")
    assert acme.meta.get("is_company") is True
    solo = next(p for p in people if p.first_name == "Solo")
    assert solo.meta.get("is_company") is False


def test_missing_store_raises_access_error(tmp_path):
    with pytest.raises(ContactsAccessError):
        read_contacts(str(tmp_path / "nonexistent"), default_region="US")


def test_probe_access_granted_on_readable_fixture(ab_root):
    assert probe_access(ab_root) == "granted"


def test_probe_access_denied_on_missing(tmp_path):
    assert probe_access(str(tmp_path / "nope")) == "denied"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_macos_contacts_reader.py -q`
Expected: FAIL — `ModuleNotFoundError: app.providers.macos_contacts`

- [ ] **Step 3: Write the reader** — `backend/app/providers/macos_contacts.py`

```python
"""Read the local macOS Contacts (AddressBook) DB, one-way and read-only.

There is no API — we open the Core Data SQLite stores directly. Schema verified
against on-disk dumps (macOS 13-15; stable at AddressBook-v22). Design is
DEFENSIVE for macOS 26: the contact entity number is discovered at runtime via
Z_PRIMARYKEY (never hardcoded), optional columns are probed, and any per-store
failure is isolated.

Access: the DB is TCC-protected — a process without Full Disk Access gets EPERM
("Operation not permitted") on open. read_contacts() raises ContactsAccessError
on a failed read so the sync can abort WITHOUT running deletion reconciliation
(a failed read must never look like "every contact was deleted"). A genuinely
empty-but-readable store returns [].
"""
from __future__ import annotations

import errno
import glob
import logging
import os
import sqlite3
import struct
from pathlib import Path

from .base import NormalizedPerson
from ..identity import canon_phone

logger = logging.getLogger("scuffed_os.macos_contacts")

DEFAULT_ROOT = "~/Library/Application Support/AddressBook"


class ContactsAccessError(Exception):
    """The AddressBook store could not be read (missing, or Full Disk Access denied)."""


def _store_paths(root: str) -> list[str]:
    base = Path(os.path.expanduser(root))
    paths = []
    top = base / "AddressBook-v22.abcddb"
    if top.exists():
        paths.append(str(top))
    paths.extend(sorted(glob.glob(str(base / "Sources" / "*" / "AddressBook-v22.abcddb"))))
    return paths


def _connect_ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _unwrap_label(raw: str | None) -> str:
    if not raw:
        return ""
    if raw.startswith("_$!<") and raw.endswith(">!$_"):
        return raw[4:-4]
    return raw


def _contact_entity(con: sqlite3.Connection) -> int | None:
    row = con.execute(
        "SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'ABCDContact'"
    ).fetchone()
    return row[0] if row else None


def probe_access(root: str = DEFAULT_ROOT) -> str:
    """'granted' | 'denied' | 'unknown' — never raises. A permission probe only;
    reads no contact data beyond a single SELECT."""
    import sys

    if sys.platform != "darwin":
        return "denied"
    paths = _store_paths(root)
    if not paths:
        return "denied"
    try:
        con = _connect_ro(paths[0])
        try:
            con.execute("SELECT 1 FROM ZABCDRECORD LIMIT 1")
        finally:
            con.close()
        return "granted"
    except sqlite3.OperationalError:
        return "denied"
    except PermissionError as exc:
        return "denied" if exc.errno == errno.EPERM else "unknown"
    except Exception:
        return "unknown"


def _read_photo(con: sqlite3.Connection, db_path: str, z_pk: int,
                photos_dir: str, source_id: str) -> tuple[str | None, bool]:
    """Extract ZTHUMBNAILIMAGEDATA (0x01 inline JPEG / 0x02 external ref) to a
    file. Degrades to (None, False) on any surprise — a photo failure is never
    fatal to the contact."""
    try:
        row = con.execute(
            "SELECT ZTHUMBNAILIMAGEDATA FROM ZABCDRECORD WHERE Z_PK = ?", (z_pk,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None, False
    blob = row[0] if row else None
    if not blob:
        return None, False
    tag = blob[0]
    if tag == 1:
        jpeg = blob[1:]
    elif tag == 2:
        name = blob[1:].rstrip(b"\x00").decode("ascii", "ignore")
        ext = Path(db_path).parent / f".{Path(db_path).stem}_SUPPORT" / "_EXTERNAL_DATA" / name
        try:
            jpeg = ext.read_bytes()
        except OSError:
            return None, False
    else:
        return None, False
    if jpeg[6:10] != b"JFIF":            # only JPEG/JFIF at this layer
        return None, False
    out_dir = Path(os.path.expanduser(photos_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in source_id if c.isalnum() or c in "-_") or str(z_pk)
    target = out_dir / f"{safe}.jpg"
    target.write_bytes(jpeg)
    return str(target), True


def _read_store(db_path: str, default_region: str,
                photos_dir: str | None) -> list[NormalizedPerson]:
    con = _connect_ro(db_path)
    try:
        ent = _contact_entity(con)
        if ent is None:
            return []
        rec_cols = _columns(con, "ZABCDRECORD")
        people: list[NormalizedPerson] = []
        rows = con.execute(
            "SELECT Z_PK, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, "
            "ZORGANIZATION, ZJOBTITLE, ZDISPLAYFLAGS "
            "FROM ZABCDRECORD WHERE Z_ENT = ?", (ent,)
        ).fetchall()
        for (z_pk, uid, first, last, nick, org, job, flags) in rows:
            phones = []
            for (num, label) in con.execute(
                "SELECT ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER "
                "WHERE ZOWNER = ? ORDER BY ZORDERINGINDEX", (z_pk,)
            ):
                if num:
                    phones.append({"value": num, "label": _unwrap_label(label)})
            emails = []
            for (addr, label) in con.execute(
                "SELECT ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS "
                "WHERE ZOWNER = ? ORDER BY ZORDERINGINDEX", (z_pk,)
            ):
                if addr:
                    emails.append({"value": addr, "label": _unwrap_label(label)})
            is_company = bool((flags or 0) & 1)
            display = (org or "").strip() if is_company else \
                " ".join(x for x in [(first or ""), (last or "")] if x).strip()
            display = display or (nick or "") or (org or "") or (uid or "")
            photo_path, has_photo = (None, False)
            if photos_dir and "ZTHUMBNAILIMAGEDATA" in rec_cols:
                photo_path, has_photo = _read_photo(con, db_path, z_pk, photos_dir, uid or str(z_pk))
            people.append(NormalizedPerson(
                source="macos_contacts",
                source_id=uid or f"zpk:{z_pk}",
                display_name=display,
                first_name=first or "", last_name=last or "",
                nickname=nick or "", organization=org or "", job_title=job or "",
                phones=phones, emails=emails,
                photo_path=photo_path, has_photo=has_photo,
                meta={"is_company": is_company},
            ))
        return people
    finally:
        con.close()


def read_contacts(root: str = DEFAULT_ROOT, *, default_region: str,
                  photos_dir: str | None = None) -> list[NormalizedPerson]:
    """Union all AddressBook stores under `root`. Raises ContactsAccessError on a
    failed/denied read; returns [] for a genuinely empty (but readable) store."""
    paths = _store_paths(root)
    if not paths:
        raise ContactsAccessError(f"no AddressBook store under {root}")
    out: list[NormalizedPerson] = []
    read_any = False
    for path in paths:
        try:
            out.extend(_read_store(path, default_region, photos_dir))
            read_any = True
        except sqlite3.OperationalError as exc:
            raise ContactsAccessError(f"cannot read {path}: {exc}") from exc
        except PermissionError as exc:
            if exc.errno == errno.EPERM:
                raise ContactsAccessError(f"Full Disk Access denied for {path}") from exc
            raise
    if not read_any:
        raise ContactsAccessError("no readable AddressBook store")
    return out
```

> `struct` import is reserved for future full-size photo decoding; safe to drop if a linter flags it. `default_region` is threaded through for symmetry (the store fills `normalized`); the reader keeps raw values.

- [ ] **Step 4: Run the reader tests to verify they pass**

Run: `cd backend && pytest tests/test_macos_contacts_reader.py -q`
Expected: PASS (6)

- [ ] **Step 5: Write the photo test** — `backend/tests/test_macos_contacts_photos.py`

```python
import sqlite3

import pytest

from app.providers.macos_contacts import read_contacts

_ENT = 19
# Minimal JFIF: SOI + APP0 'JFIF\0' marker, enough for the bytes[6:10]=='JFIF' check.
_JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10]) + b"JFIF\x00" + b"\x00" * 8


def _store(path, blob):
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);"
        "CREATE TABLE ZABCDRECORD (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZUNIQUEID TEXT,"
        " ZFIRSTNAME TEXT, ZLASTNAME TEXT, ZNICKNAME TEXT, ZORGANIZATION TEXT, ZJOBTITLE TEXT,"
        " ZDISPLAYFLAGS INTEGER, ZTHUMBNAILIMAGEDATA BLOB);"
        "CREATE TABLE ZABCDPHONENUMBER (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZFULLNUMBER TEXT, ZLABEL TEXT, ZORDERINGINDEX INTEGER);"
        "CREATE TABLE ZABCDEMAILADDRESS (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZADDRESS TEXT, ZLABEL TEXT, ZORDERINGINDEX INTEGER);"
    )
    con.execute("INSERT INTO Z_PRIMARYKEY VALUES (?, 'ABCDContact')", (_ENT,))
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS, ZTHUMBNAILIMAGEDATA)"
                " VALUES (1, ?, 'UID-P:ABPerson', 'Pic', 0, ?)", (_ENT, blob))
    con.commit()
    con.close()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "AddressBook"
    r.mkdir()
    return r


def test_inline_photo_extracted(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + _JPEG)
    people = read_contacts(str(root), default_region="US", photos_dir=str(tmp_path / "photos"))
    p = people[0]
    assert p.has_photo is True
    assert p.photo_path and p.photo_path.endswith(".jpg")


def test_non_jfif_blob_falls_back_to_no_photo(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + b"not a jpeg at all")
    people = read_contacts(str(root), default_region="US", photos_dir=str(tmp_path / "photos"))
    assert people[0].has_photo is False


def test_unknown_prefix_byte_no_crash(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x09" + _JPEG)
    people = read_contacts(str(root), default_region="US", photos_dir=str(tmp_path / "photos"))
    assert people[0].has_photo is False
```

- [ ] **Step 6: Run photo tests + full suite + commit**

Run: `cd backend && pytest tests/test_macos_contacts_photos.py tests/test_macos_contacts_reader.py -q` then `pytest -q` (report count)
```bash
git add backend/app/providers/macos_contacts.py backend/tests/test_macos_contacts_reader.py backend/tests/test_macos_contacts_photos.py
git commit -m "feat(people): read-only macOS AddressBook reader + photo extraction + FDA probe (M10 s1)"
```

---

## Task 5: Sync engine (`contacts_sync.py`) + config + lifespan wiring

**Files:**
- Modify: `backend/app/config.py` (add `_default_region()` + settings)
- Create: `backend/app/contacts_sync.py`
- Modify: `backend/app/main.py` (import + lifespan + shutdown tuple)
- Create: `backend/tests/test_contacts_sync.py`

**Interfaces:**
- Consumes: `read_contacts`, `probe_access`, `ContactsAccessError` (Task 4); `store.upsert_person`, `store.reconcile_people` (Task 3).
- Produces: `contacts_sync.tick(now=None) -> int`; `async trigger() -> int`; `async run_loop() -> None`; `configure(override="unset") -> None`.

- [ ] **Step 1: Add config** — `backend/app/config.py`

Above `class Settings`, add the helper:
```python
def _default_region() -> str:
    import locale
    import re
    import subprocess

    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        m = re.search(r"_([A-Z]{2})", os.environ.get(var, ""))
        if m:
            return m.group(1)
    try:
        m = re.search(r"_([A-Z]{2})", locale.getlocale()[0] or "")
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLocale"],
                             capture_output=True, text=True, timeout=2)
        m = re.search(r"_([A-Z]{2})", out.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "US"
```
(Ensure `import os` exists at the top of config.py.) In the `Settings` body, after the finance-sync block (`plaid_backfill_days`), add:
```python
    # ---- M10 Contacts (local macOS AddressBook) ----
    # Background contacts-sync (mirrors finance_sync_enabled / finance_sync_seconds).
    # Contacts change slowly; a gentle cadence is fine.
    contacts_sync_enabled: bool = True
    contacts_sync_seconds: int = 21600            # 6 h
    contacts_default_region: str = _default_region()  # ISO-3166 alpha-2 for E.164 normalization
    contacts_photos_dir: str = "./data/contact_photos"
```
If Task 3 already added a placeholder `contacts_default_region: str = "US"`, replace it with the line above.

- [ ] **Step 2: Write the failing test** — `backend/tests/test_contacts_sync.py`

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import contacts_sync
from app.db import Base
from app.providers import macos_contacts
from app.providers.base import NormalizedPerson
from app.store import store


@pytest.fixture(autouse=True)
def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    store.configure(sessionmaker(eng))
    yield
    store.configure(None)
    contacts_sync.configure("unset")


def test_tick_upserts_then_reconciles(monkeypatch):
    batch = [NormalizedPerson(source="macos_contacts", source_id="A", display_name="A"),
             NormalizedPerson(source="macos_contacts", source_id="B", display_name="B")]
    monkeypatch.setattr(macos_contacts, "read_contacts", lambda *a, **k: batch)
    assert contacts_sync.tick() == 2
    assert len(store.list_people()) == 2
    # next pass: B disappears -> soft-deleted, not hard-deleted
    monkeypatch.setattr(macos_contacts, "read_contacts",
                        lambda *a, **k: [batch[0]])
    contacts_sync.tick()
    assert {p["display_name"] for p in store.list_people()} == {"A"}
    assert len(store.list_people(include_removed=True)) == 2


def test_failed_read_does_not_reconcile(monkeypatch):
    batch = [NormalizedPerson(source="macos_contacts", source_id="A", display_name="A")]
    monkeypatch.setattr(macos_contacts, "read_contacts", lambda *a, **k: batch)
    contacts_sync.tick()
    # Now the read FAILS (FDA revoked). Must NOT soft-delete everyone.
    def boom(*a, **k):
        raise macos_contacts.ContactsAccessError("denied")
    monkeypatch.setattr(macos_contacts, "read_contacts", boom)
    assert contacts_sync.tick() == 0
    assert len(store.list_people()) == 1   # A still visible


def test_configure_override():
    class Fake:
        def tick(self, now=None):
            return 99
    contacts_sync.configure(Fake())
    assert contacts_sync.tick() == 99
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && pytest tests/test_contacts_sync.py -q`
Expected: FAIL — `ModuleNotFoundError: app.contacts_sync`

- [ ] **Step 4: Write the sync engine** — `backend/app/contacts_sync.py`

```python
"""Contacts sync engine (M10 s1) — a token-less clone of moodle_sync.

Reads the local macOS AddressBook via providers.macos_contacts (no network, no
OAuth, no cursor) and upserts every contact into the people table, then soft-
deletes contacts that vanished. The tick NEVER crashes. A FAILED read
(ContactsAccessError — e.g. Full Disk Access denied) is logged and skips
reconciliation entirely, so a permission blip never looks like "every contact
was deleted" (mirrors M7's feature-absent sync-abort).

Test seam: configure(fake) installs an object with .tick() that tick() delegates
to; configure(None)/"unset" run the real pass.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import settings
from .providers import macos_contacts
from .store import store

logger = logging.getLogger("scuffed_os.contacts_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def tick(now: datetime | None = None) -> int:
    """One contacts pass. Returns records upserted (+ reconciled). Never crashes."""
    if _override not in ("unset", None) and hasattr(_override, "tick"):
        return _override.tick(now)  # type: ignore[union-attr]
    now = now or _utcnow()
    try:
        people = macos_contacts.read_contacts(
            settings.__dict__.get("addressbook_root", macos_contacts.DEFAULT_ROOT),
            default_region=settings.contacts_default_region,
            photos_dir=settings.contacts_photos_dir,
        )
    except macos_contacts.ContactsAccessError:
        logger.info("contacts read unavailable (no Full Disk Access?); skipping (no reconcile)")
        return 0
    except RuntimeError as exc:
        if "DATABASE_URL" in str(exc):
            return 0
        logger.exception("contacts read failed")
        return 0
    except Exception:
        logger.exception("contacts read failed")
        return 0

    count = 0
    seen: list[str] = []
    for person in people:
        try:
            store.upsert_person(person)
            seen.append(person.source_id)
            count += 1
        except Exception:
            logger.exception("upsert_person failed for %s", person.source_id)
    try:
        count += store.reconcile_people("macos_contacts", seen, now)
    except Exception:
        logger.exception("reconcile_people failed")
    return count


async def trigger() -> int:
    """Run one pass off the event loop. Awaited by POST /api/people/sync."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    logger.info("contacts sync loop started (every %ss)", settings.contacts_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d contact record(s)", synced)
        except Exception:
            logger.exception("contacts sync tick failed")
        await asyncio.sleep(settings.contacts_sync_seconds)
```

- [ ] **Step 5: Wire the lifespan** — `backend/app/main.py`

- Add `contacts_sync` to the top-level `from . import ...` that already imports `moodle_sync` (grep `moodle_sync` in main.py imports).
- In `lifespan`, after `finance_task: asyncio.Task | None = None` add: `    contacts_task: asyncio.Task | None = None`
- After the `if settings.finance_sync_enabled:` block add:
```python
    if settings.contacts_sync_enabled:
        contacts_task = asyncio.create_task(contacts_sync.run_loop())
```
- Add `contacts_task` to the shutdown tuple: `for task in (reminder_task, fitness_task, email_task, moodle_task, finance_task, contacts_task):`

- [ ] **Step 6: Run the sync tests to verify they pass**

Run: `cd backend && pytest tests/test_contacts_sync.py -q`
Expected: PASS (3)

- [ ] **Step 7: Full suite + commit**

Run: `cd backend && pytest -q` (report count)
```bash
git add backend/app/contacts_sync.py backend/app/config.py backend/app/main.py backend/tests/test_contacts_sync.py
git commit -m "feat(people): token-less contacts sync engine w/ feature-absent abort + lifespan wiring (M10 s1)"
```

---

## Task 6: People router + schemas + api.js + photo endpoint

**Files:**
- Modify: `backend/app/schemas.py` (Person trio)
- Create: `backend/app/routers/people.py`
- Modify: `backend/app/main.py` (router import + include)
- Modify: `frontend/src/lib/api.js`
- Create: `backend/tests/test_people_api.py`

**Interfaces:**
- Consumes: store person methods (Task 3), `contacts_sync.tick` (Task 5).
- Produces: REST `GET/POST /api/people`, `GET/PATCH/DELETE /api/people/{id}`, `POST /api/people/sync`, `GET /api/people/{id}/photo`; `PersonOut/Create/Update`.

- [ ] **Step 1: Add schemas** — `backend/app/schemas.py` (after the Memory block)

```python
# ---- People (M10) ---------------------------------------------------------
class PersonOut(BaseModel):
    id: int
    source: str
    source_id: str
    display_name: str
    first_name: str
    last_name: str
    nickname: str
    organization: str
    job_title: str
    phones: list[dict]
    emails: list[dict]
    has_photo: bool
    relationship: str | None = None
    relationship_strength: int | None = None
    notes: str | None = None
    pinned: bool
    last_contacted_at: datetime | None = None
    removed_from_source_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PersonCreate(BaseModel):
    display_name: str = Field(min_length=1)
    phones: list[dict] = []
    emails: list[dict] = []
    relationship: str | None = None
    relationship_strength: int | None = None
    notes: str | None = None
    pinned: bool = False


class PersonUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    phones: list[dict] | None = None
    emails: list[dict] | None = None
    relationship: str | None = None
    relationship_strength: int | None = None
    notes: str | None = None
    pinned: bool | None = None
    last_contacted_at: datetime | None = None
```

- [ ] **Step 2: Write the failing test** — `backend/tests/test_people_api.py`

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    store.configure(sessionmaker(eng))
    yield
    store.configure(None)


def test_people_crud_roundtrip():
    c = TestClient(app)
    assert c.get("/api/people").json() == []
    created = c.post("/api/people", json={"display_name": "Ada Lovelace"}).json()
    assert created["source"] == "manual"
    pid = created["id"]
    patched = c.patch(f"/api/people/{pid}", json={"relationship": "Friend"}).json()
    assert patched["relationship"] == "Friend"
    assert c.get(f"/api/people/{pid}").json()["display_name"] == "Ada Lovelace"
    assert c.delete(f"/api/people/{pid}").status_code == 204
    assert c.get(f"/api/people/{pid}").status_code == 404


def test_sync_endpoint_shape(monkeypatch):
    from app import contacts_sync
    monkeypatch.setattr(contacts_sync, "tick", lambda: 3)
    c = TestClient(app)
    body = c.post("/api/people/sync").json()
    assert body["synced"] == 3
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && pytest tests/test_people_api.py -q`
Expected: FAIL — 404 on `/api/people` (router not registered)

- [ ] **Step 4: Write the router** — `backend/app/routers/people.py`

```python
"""People CRUD (M10 s1). The People/CRM screen and (later) the messaging slices
read/write these rows. Contacts are synced one-way from macOS via
contacts_sync; manual people are user-created here."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from .. import contacts_sync
from ..schemas import PersonCreate, PersonOut, PersonUpdate
from ..store import store

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("", response_model=list[PersonOut])
def list_people() -> list[dict]:
    return store.list_people()


@router.get("/{person_id}", response_model=PersonOut)
def get_person(person_id: int) -> dict:
    p = store.get_person(person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return p


@router.post("", response_model=PersonOut, status_code=201)
def create_person(body: PersonCreate) -> dict:
    return store.create_person(body.model_dump())


@router.patch("/{person_id}", response_model=PersonOut)
def update_person(person_id: int, body: PersonUpdate) -> dict:
    updated = store.update_person(person_id, body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return updated


@router.delete("/{person_id}", status_code=204)
def delete_person(person_id: int) -> Response:
    if not store.delete_person(person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    return Response(status_code=204)


@router.post("/sync")
def sync_now() -> dict:
    """Run one contacts sync pass now (manual/test). Reads never depend on it."""
    return {"synced": contacts_sync.tick(), "providers": ["macos_contacts"]}


@router.get("/{person_id}/photo")
def get_person_photo(person_id: int) -> FileResponse:
    p = store.get_person(person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Person not found")
    row = store._person_photo_path(person_id)  # small helper returning photo_path or None
    if not row or not Path(os.path.expanduser(row)).exists():
        raise HTTPException(status_code=404, detail="No photo")
    return FileResponse(os.path.expanduser(row), media_type="image/jpeg")
```

Add the tiny helper to `store.py` (photo_path is intentionally not in `_person_dict`, so expose it explicitly):
```python
    def _person_photo_path(self, person_id: int) -> str | None:
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            return row.photo_path if row is not None else None
```

- [ ] **Step 5: Register the router** — `backend/app/main.py`

- Add `people,` to the `from .routers import (...)` tuple (alphabetically after `oauth,`).
- Add `app.include_router(people.router)` after `app.include_router(memory.router)`.

- [ ] **Step 6: Add api.js methods** — `frontend/src/lib/api.js` (after the memories block)

```js
  // People / CRM (M10) — real contact rows (macOS Contacts sync + manual).
  listPeople: () => request('/api/people'),
  getPerson: (id) => request(`/api/people/${id}`),
  createPerson: (person) => request('/api/people', {
    method: 'POST',
    body: JSON.stringify(typeof person === 'string' ? { display_name: person } : person),
  }),
  updatePerson: (id, patch) => request(`/api/people/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deletePerson: (id) => request(`/api/people/${id}`, { method: 'DELETE' }),
  syncContacts: () => request('/api/people/sync', { method: 'POST' }),
```

- [ ] **Step 7: Run the api tests + full suite + commit**

Run: `cd backend && pytest tests/test_people_api.py -q` then `pytest -q` (report count)
```bash
git add backend/app/routers/people.py backend/app/schemas.py backend/app/main.py backend/app/store.py backend/tests/test_people_api.py frontend/src/lib/api.js
git commit -m "feat(people): CRUD + /sync + /photo router, schemas, api.js methods (M10 s1)"
```

---

## Task 7: `macos_contacts` connector card (`auth_kind="local"` + FDA probe)

**Files:**
- Modify: `backend/app/schemas.py` (widen `ConnectorInfo` Literals + `access`)
- Modify: `backend/app/routers/connectors.py` (catalog + probe + `_contacts_connector`)
- Modify: `backend/tests/test_connectors.py` (update the order-lock assertion)
- Create/extend: `backend/tests/test_connectors_contacts.py`

**Interfaces:**
- Consumes: `macos_contacts.probe_access` (Task 4).
- Produces: a 5th `ConnectorInfo` with `name="macos_contacts"`, `auth_kind="local"`, `access ∈ {granted,denied,unknown}`.

- [ ] **Step 1: Widen the schema** — `backend/app/schemas.py`

```python
    name: Literal["google", "whoop", "moodle", "plaid", "macos_contacts"]
    ...
    auth_kind: Literal["oauth", "token", "link", "local"]
    ...
    access: Literal["granted", "denied", "unknown"] = "unknown"   # macos_contacts only
```
(Keep `access` defaulted so the other four constructions stay valid.)

- [ ] **Step 2: Write the failing test** — `backend/tests/test_connectors_contacts.py`

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import connectors


def _card(client):
    return next(c for c in client.get("/api/connectors").json() if c["name"] == "macos_contacts")


def test_contacts_card_granted(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_access", lambda: "granted")
    card = _card(TestClient(app))
    assert card["auth_kind"] == "local"
    assert card["access"] == "granted"
    assert card["status"] == "connected"


def test_contacts_card_denied(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_access", lambda: "denied")
    card = _card(TestClient(app))
    assert card["access"] == "denied"
    assert card["status"] == "not_connected"
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && pytest tests/test_connectors_contacts.py -q`
Expected: FAIL — no `macos_contacts` card / no `_contacts_access`.

- [ ] **Step 4: Implement** — `backend/app/routers/connectors.py`

Append to `_CATALOG`:
```python
    ("macos_contacts", "Apple Contacts", "local"),
```
In `_configured`, before the final `return False`:
```python
    if name == "macos_contacts":
        import sys
        return sys.platform == "darwin"
```
Add helpers near `_plaid_connector`:
```python
def _contacts_access() -> str:
    from ..providers import macos_contacts
    from ..config import settings

    return macos_contacts.probe_access(
        getattr(settings, "addressbook_root", macos_contacts.DEFAULT_ROOT)
    )


def _contacts_connector() -> ConnectorInfo:
    access = _contacts_access()
    status = "connected" if access == "granted" else "not_connected"
    return ConnectorInfo(
        name="macos_contacts", label="Apple Contacts", auth_kind="local",
        configured=_configured("macos_contacts"), status=status,
        connected_at=None, provider_user_id=None, can_write_email=None,
        access=access, items=[],
    )
```
In `list_connectors`, add the short-circuit alongside plaid's:
```python
        if name == "macos_contacts":
            out.append(_contacts_connector())
            continue
```

- [ ] **Step 5: Update the order-lock test** — `backend/tests/test_connectors.py`

Change the `auth_kind` assertion (~line 36) to include the new card:
```python
    assert [c["auth_kind"] for c in body] == ["oauth", "oauth", "token", "link", "local"]
```
(Bump any connector-count assertion 4 → 5.)

- [ ] **Step 6: Run tests + full suite + commit**

Run: `cd backend && pytest tests/test_connectors_contacts.py tests/test_connectors.py -q` then `pytest -q` (report count)
```bash
git add backend/app/schemas.py backend/app/routers/connectors.py backend/tests/test_connectors_contacts.py backend/tests/test_connectors.py
git commit -m "feat(people): macOS Contacts connector card (auth_kind=local, FDA probe) (M10 s1)"
```

---

## Task 8: Frontend — People screen + Connectors `local` branch

Frontend has no test runner; the deliverable is verified in the browser preview (run-scuffedos skill / preview_start + read_page/screenshot).

**Files:**
- Modify: `frontend/src/screens/CRMScreen.jsx` (full rewrite to real data)
- Modify: `frontend/src/screens/ConnectorsPanel.jsx` (`local` branch)

- [ ] **Step 1: Rewrite `CRMScreen.jsx`** — real data, keeping the `kit-grid` layout + all `kit-*` classes

```jsx
/* Scuffed OS — Personal CRM (M10: real people from the local Contacts sync) */
import React from 'react'
import { Card, Avatar, Badge, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const TINTS = ['sky', 'plum', 'green', 'honey', 'clay', 'neutral']
const tintFor = (p) => TINTS[(p.id || 0) % TINTS.length]

export function CRMScreen() {
  const [people, setPeople] = React.useState(null)
  const [error, setError] = React.useState('')

  const refresh = React.useCallback(() => {
    api.listPeople()
      .then((p) => { setPeople(p); setError('') })
      .catch((e) => setError(e?.message || 'Failed to load people'))
  }, [])
  React.useEffect(() => { refresh() }, [refresh])

  if (error && !people) return <Card variant="flat"><p className="kit-muted">{error}</p></Card>
  if (!people) return <Card variant="flat"><p className="kit-muted">Loading…</p></Card>

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1.5fr 1fr' }}>
      <Card title="People" eyebrow={`${people.length} contacts`} action={
        <div className="kit-search" style={{ width: 180 }}><Icon name="search" /><input placeholder="Search people" /></div>
      }>
        {people.length === 0 ? (
          <div className="kit-stack" style={{ alignItems: 'center', padding: 24 }}>
            <Icon name="users" />
            <p className="kit-row__title">No contacts yet</p>
            <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
              Sync your macOS Contacts from Settings › Connectors to get started.
            </p>
          </div>
        ) : people.map((p) => (
          <div className="kit-person" key={p.id}>
            <Avatar name={p.display_name}
              src={p.has_photo ? `/api/people/${p.id}/photo` : undefined}
              tint={tintFor(p)} />
            <div className="kit-person__main">
              <p className="kit-person__name">
                {p.display_name}
                {p.relationship && <Badge color="sky">{p.relationship}</Badge>}
              </p>
              <p className="kit-person__sub">
                {p.emails?.[0]?.value || p.phones?.[0]?.value || p.organization || '—'}
              </p>
            </div>
            <IconButton label="Draft a note"><Icon name="pen-line" /></IconButton>
          </div>
        ))}
      </Card>

      <div className="kit-col">
        <Card title="Reach out" eyebrow="Assistant nudges" variant="sunken">
          <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
            Nudges arrive once the messaging slices land.
          </p>
        </Card>
      </div>
    </div>
  )
}
```

> If `Avatar` doesn't accept a `src` prop, extend it in `components/ui.jsx` to render an `<img src>` (falling back to initials when `src` is absent or errors). Confirm the prop name during implementation; the stub only used `name`/`tint`.

- [ ] **Step 2: Add the `local` branch to `ConnectorsPanel.jsx`**

- Exempt `local` from the credential gate (line ~160): `busy === c.name || (c.auth_kind !== 'token' && c.auth_kind !== 'local' && (!c.configured || !vaultOk))`.
- Add a new branch after the `link` block:
```jsx
            {/* Local connector: macOS Contacts (Full Disk Access) */}
            {c.auth_kind === 'local' && (
              <div className="kit-stack" style={{ gap: 8 }}>
                <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
                  {c.access === 'granted'
                    ? 'Contacts access granted.'
                    : 'Grant Full Disk Access, then Sync.'}
                </span>
                <div className="kit-inline" style={{ gap: 8 }}>
                  {c.access !== 'granted' && (
                    <Button variant="secondary" size="sm"
                      onClick={() => openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles')
                        .catch((e) => setError(e?.message || 'Could not open System Settings'))}>
                      Grant Full Disk Access
                    </Button>
                  )}
                  <Button variant="primary" size="sm" disabled={busy === c.name}
                    onClick={() => { setBusy(c.name); api.syncContacts().then(() => refresh()).catch((e) => setError(e?.message || 'Sync failed')).finally(() => setBusy('')) }}>
                    Sync now
                  </Button>
                </div>
              </div>
            )}
```

- [ ] **Step 3: Verify in the browser** (run-scuffedos skill or preview_start)

- Start the app; open Settings › Connectors → confirm the "Apple Contacts" card renders with the access line + Grant/Sync buttons.
- Open People → confirm it shows the empty state (or, if you granted FDA and synced, real contacts + photos).
- Check `read_console_messages` for errors; screenshot both surfaces.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/CRMScreen.jsx frontend/src/screens/ConnectorsPanel.jsx frontend/src/components/ui.jsx
git commit -m "feat(people): real People screen + macOS Contacts connector card (M10 s1)"
```

---

## Task 9: Docs + privacy disclosure

**Files:**
- Create: `docs/people.md`
- Modify: `docs/privacy-policy.md` (add the macOS Contacts local-access disclosure), then run the `publish-privacy-policy` skill to mirror it.
- Modify: `README.md` (connector list).

- [ ] **Step 1: Write `docs/people.md`** — model, one-way sync + field ownership, soft deletion, FDA flow, `resolve_handle`, config (`contacts_sync_*`, `contacts_default_region`, `contacts_photos_dir`).

- [ ] **Step 2: Add the privacy disclosure** to `docs/privacy-policy.md`: a "macOS Contacts (local, on-device)" entry — what's read (names/phones/emails/photos), that it stays on-device, requires Full Disk Access, one-way, never written back. Bump the effective date.

- [ ] **Step 3: Publish** — invoke the `publish-privacy-policy` skill (gist + corp site). Confirm both mirrors updated.

- [ ] **Step 4: Update `README.md`** connector list to include Apple Contacts (local).

- [ ] **Step 5: Commit**

```bash
git add docs/people.md docs/privacy-policy.md README.md
git commit -m "docs(people): people.md + macOS Contacts privacy disclosure (M10 s1)"
```

---

## Self-Review (spec coverage)

- Person/CRM model (spec §4.1) → Task 2. phones/emails `{value,label,normalized}`, CRM-native, soft-delete column → Tasks 2–3.
- Reader (§4.2), multi-source union, `Z_ENT` discovery, label unwrap, company/NULL → Task 4. `ZABCDMESSAGINGADDRESS`/`ZABCDRELATEDNAME` non-mapping → deferred (documented in spec; not required for slice-1 acceptance).
- identity.py / phonenumberslite (§4.3) → Task 1.
- Photos in-scope + initials fallback (§4.4) → Task 4 (extract) + Task 6 (serve) + Task 8 (render).
- Store upsert/CRUD/`resolve_handle→list`/`PersonHandle` (§4.5) → Task 3.
- Sync engine + feature-absent abort + soft deletion (§4.6, §4.6a) → Task 5.
- FDA flow, EPERM detection, deep link, `local` card (§5, §4.8) → Tasks 4, 7, 8.
- Router/schemas/frontend (§4.7, §4.9) → Tasks 6, 8.
- Migration 0010 (§4.10) → Task 2.
- Privacy (§8) → Task 9.
- Testing (§9) → each task's tests + fixture `.abcddb`.
- No-auto-send principle (§2.G) → Global Constraints (recorded; enforced in later slices).

**Deferred (not in this slice, per spec):** cross-source dedup via `ZLINKID`; contact→message timeline; two-way editing; the on-device FDA responsible-process acceptance check (manual, on the signed bundle — cannot run in `tauri dev`).
