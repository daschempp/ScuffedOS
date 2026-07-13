# People/CRM + macOS Contacts Sync — Implementation Plan (Messaging M10, Slice 1) — Rev 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a source-aware People/CRM whose structured contact fields are persisted to the **configured PostgreSQL database** (local *or* remote/self-hosted), populated by a **local, read-only** import of the macOS AddressBook — behind explicit app-level consent, with complete-snapshot sync semantics and a `resolve_handle()` seam for the iMessage slice.

**Architecture:** Mirror the existing "synced-connector" recipe (Email/Moodle): a `Person` table keyed `(owner, source, source_id)`, a **local read-only** reader (`providers/macos_contacts.py`) that returns a typed `ContactsSnapshot`, a token-less `contacts_sync.py` engine that applies snapshots **transactionally** under process + database advisory locks, a source-aware CRUD `routers/people.py`, and a fifth Connectors card (`auth_kind="local"`) gated by app consent + a Full-Disk-Access probe. Structured data lands in the configured PostgreSQL server (which may be remote); extracted photos stay on the backend host's App Support filesystem.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL (SQLite in tests), `phonenumberslite` (new), Vite/React + Vitest/RTL (new frontend test runner).

## Persistence & Privacy Contract (authoritative — use this wording; do NOT reintroduce "on-device/all-local")

- Contacts are read **locally and read-only** from the macOS AddressBook database on the machine running the backend.
- Structured contact fields (names, phones, emails, organization, job title, metadata, handle index) are **persisted to the configured PostgreSQL database**, which may run **locally (loopback) or on a remote/self-hosted server**. **When PostgreSQL is remote, contact data travels over the network to that server.**
- Extracted contact **photos remain on the backend host** under the application's App Support directory (they are NOT stored in PostgreSQL).
- This slice sends Contacts data to **no AI providers and no third-party Contacts APIs**.
- `auth_kind="local"` describes the **source and authorization mechanism** (a local, FDA-gated read), **not data residency**.
- **TLS is required for any non-loopback PostgreSQL connection** (`sslmode=require` or stronger); a non-loopback DSN without TLS is a misconfiguration the app surfaces. **Connection strings and credentials must never appear in logs** (log redacted host only).
- **Single backend host per database** in slice 1: photos live on that host's filesystem; the process-level lock is per-host and is backed by a PostgreSQL advisory lock for cross-process/host safety. Multi-host/shared-DB (shared object storage for photos + a distributed sync lease) is explicitly **out of scope**, noted for a later slice.
- **Remote DSNs are supported and must NOT be rejected.** An unreachable remote PostgreSQL server is a **failed sync**, never an "empty source".

## Global Constraints

- Target macOS 26.x for the reader (schema stable at `AddressBook-v22`; probe tables/columns, never hardcode entity numbers).
- Python 3.14 (`locale.getlocale()`, not the deprecated `getdefaultlocale()`).
- New deps: `phonenumberslite` (backend, vendored via `scripts/vendor-python.sh`); Vitest + `@testing-library/react` (frontend dev).
- Alembic head is `0009`; this slice adds exactly one migration `0010_people.py` (`down_revision="0009"`) creating `people`, `person_handle`, and `contacts_sync_state`.
- **Contacts import defaults to DISABLED.** No probing, no background sync, and no reads happen until the user explicitly enables (connects) it. FDA status is tracked **separately** from app consent.
- **Complete-snapshot reconciliation:** soft-deletion reconciliation runs **only** when a snapshot is `COMPLETE_*` (every discovered store read successfully) **and** no per-record apply error occurred. A failed/partial/denied/unsupported read never soft-deletes.
- **FDA detection:** attempt an actual read; `PermissionError` errno 1 (EPERM) ⇒ access denied. Never trust `os.access()`.
- **Sync-owned vs CRM-native ownership preserved:** sync writes only sync-owned identity fields; CRM-native fields (`relationship`, `relationship_strength`, `notes`, `pinned`, `last_contacted_at`) are ScuffedOS-owned and never touched by sync.
- **Governing principle (future slices):** no auto-send, ever.
- **Per-repo rules:** TDD (failing test first); run `.venv/bin/python -m pytest` after each task and report the count (**baseline = 703 collected**); function-local `from .config import settings` in store methods; stamp `owner=settings.owner`; frequent commits.

## Design Contract (shared types & behaviors — every task must match these names/signatures)

### Reader result — `ContactsSnapshot` (in `providers/macos_contacts.py`)
```python
from enum import Enum
from dataclasses import dataclass, field

class SnapshotStatus(str, Enum):
    COMPLETE_NONEMPTY = "complete_nonempty"   # all discovered stores read OK; >=1 contact
    COMPLETE_EMPTY = "complete_empty"         # all discovered stores read OK; zero contacts
    ACCESS_DENIED = "access_denied"           # EPERM / Full Disk Access missing
    UNSUPPORTED_SCHEMA = "unsupported_schema" # missing ABCDContact entity or required table/column
    MISSING_STORE = "missing_store"           # no AddressBook store files present
    PARTIAL_READ = "partial_read"             # >=1 store read but >=1 failed -> reconciliation unsafe
    IO_ERROR = "io_error"                     # sqlite corruption / generic I/O failure

@dataclass
class ContactsSnapshot:
    status: SnapshotStatus
    people: list                              # list[NormalizedPerson]; only for COMPLETE_*
    stores_total: int = 0
    stores_read: int = 0
    store_ids: list = field(default_factory=list)   # stable ids of stores read OK
    error: str | None = None                  # redacted, never a DSN/credential
```
- `read_snapshot(root=DEFAULT_ROOT, *, region: str, photos_dir: str, enabled: bool = True) -> ContactsSnapshot` is the ONLY public read entry. It never raises for control flow; it classifies. A missing `ABCDContact` entity or a missing required table ⇒ `UNSUPPORTED_SCHEMA` (**never** `COMPLETE_EMPTY`). `[]` people is only ever `COMPLETE_EMPTY`.
- `probe_access(root=DEFAULT_ROOT) -> str` → `"granted"|"denied"|"unknown"` (permission probe only; never raises).

### Sync result — `SyncResult`
```python
@dataclass
class SyncResult:
    status: str          # 'ok' | 'empty' | 'access_denied' | 'unsupported' | 'partial' | 'error' | 'disabled'
    access: str          # 'granted' | 'denied' | 'unknown'
    imported: int = 0
    updated: int = 0
    removed: int = 0
    last_sync_at: object | None = None   # datetime
    last_error: str | None = None
```

### Transactional apply — `store.apply_contacts_snapshot(snapshot, now) -> SyncResult`
- If `snapshot.status not in {COMPLETE_NONEMPTY, COMPLETE_EMPTY}`: write status/last_error to `contacts_sync_state`, perform **no** row writes, return a SyncResult reflecting the status (e.g. `access_denied`/`unsupported`/`partial`/`error`). For `ACCESS_DENIED` while rows already exist, also mark those rows' state `stale` (status='stale') — do NOT soft-delete.
- Else (COMPLETE_*): in **one DB transaction**, under a **process lock** AND (on PostgreSQL) a transaction-scoped **advisory lock** `pg_advisory_xact_lock(<stable key>)`: upsert every person, rebuild each person's handle-index rows, and — only if no per-record apply error occurred — reconcile (soft-delete `source='macos_contacts'` rows whose `source_id` is absent from the snapshot). Update `contacts_sync_state`. Return counts. On SQLite (tests) the advisory lock is a no-op.
- **Skip reconciliation** if any validation/transform/photo error made the apply incomplete — still commit the successful upserts and record `status='partial'`. An **infrastructure/DB error** (`SQLAlchemyError`/`OperationalError`) is NOT swallowed as `partial`: it **propagates so the whole transaction rolls back atomically**.

### Consent & lifecycle — `contacts_sync_state` table (one row per owner)
Columns: `owner` (unique), `enabled: bool = False` (**app consent, default off**), `status: str` ∈ {`disabled`,`access_denied`,`ready`,`syncing`,`stale`,`error`}, `access: str` ∈ {`granted`,`denied`,`unknown`}, `normalization_region: str | None` (persisted region used to canonicalize handles — set at enable/first sync; a later system-locale change does NOT retroactively alter it), `last_sync_at`, `last_error`, `enabled_at`, `created_at`, `updated_at`.
Lifecycle:
- **Enable/connect** (`POST /api/people/contacts/enable`): requires the storage disclosure acknowledged (frontend gates it); sets `enabled=True`, stamps `enabled_at` + `normalization_region = settings.contacts_default_region`, then kicks a sync.
- **Disconnect** (`POST /api/people/contacts/disconnect`): sets `enabled=False`; stops future reads/syncs; **does NOT delete rows** (existing CRM data preserved; status→`disabled`).
- **Forget imported data** (`POST /api/people/contacts/forget`, confirmed): deletes imported (`source='macos_contacts'`) rows + their `person_handle` rows + extracted photos. **CRM-native survival rule:** a person carrying CRM-native data (any of relationship/strength/notes/pinned/last_contacted_at) is **converted to a `source='manual'` tombstone** retaining `display_name` + the CRM-native fields (identity fields + photo cleared); people with no CRM-native data are fully deleted.
- **FDA revoked while enabled:** access→`denied`, status→`stale`; existing rows are **preserved** (never soft-deleted by a denied read).
- Background sync + probe are no-ops while `enabled=False`.

### Typed handle schemas (Pydantic; replace `list[dict]`)
```python
class PhoneEntry(BaseModel):
    value: str = Field(min_length=1)
    label: str = ""
    normalized: str | None = None

class EmailEntry(BaseModel):
    value: str = Field(min_length=1)
    label: str = ""
    normalized: str | None = None
```
`PersonOut.phones: list[PhoneEntry]`, `emails: list[EmailEntry]`. Store fills `normalized` from `app.identity`.

### Source ID namespacing (reader)
`store_id` = stable per-store identifier: the `Sources/<UUID>` folder name, or `"local"` for the top-level store (fall back to `sha1(abspath)` if neither). `source_id = sha1(f"{store_id}:{zuniqueid or ('zpk:'+str(z_pk))}").hexdigest()` (fits `String(128)`; never an unqualified `zpk:1`). Keep raw `{store_id, zuniqueid, z_pk}` in `meta` for debugging.

### Region persistence
Canonicalization region comes from `contacts_sync_state.normalization_region` (persisted), NOT live `settings` at query time, so a locale change doesn't silently re-resolve existing handles. `resolve_handle` and handle re-indexing read the persisted region (fall back to `settings.contacts_default_region` if unset).

### Photo storage
- Root resolves through **App Support** (`os.path.expanduser(settings.app_support_dir)/contact_photos`), NOT `./data/...`. Config field: `contacts_photos_dir` may be relative or absolute; if relative, resolve under App Support root.
- `photo_key` (opaque, RELATIVE, stored in PostgreSQL) = `f"{sha256(store_id+':'+source_id)}.{ext}"`; served by resolving `key` against the photos root with a **containment check** (resolved real path must be under the resolved root; reject symlink/`..` traversal).
- **Atomic write** (temp file + `os.replace`). **Detect the real media type** from magic bytes (JPEG/PNG/HEIC/…) → correct `Content-Type` and extension; do not assume JFIF.
- Failures (permission, disk-full, invalid filename, malformed image) are caught per-photo and **never abort the snapshot** (person imported without a photo).
- **Cleanup** superseded/deleted/rolled-back/orphaned photo files on re-sync, on forget, and on delete.

### Locking
`apply_contacts_snapshot` and any mutation path go through a module-level process lock; on PostgreSQL also take a transaction-scoped `pg_advisory_xact_lock`. Manual `POST /sync` and the background loop share this locked path so overlapping ticks serialize. SQLite → advisory lock is a no-op.

### Testing/CI seam
- Reuse the repo's shared SQLite/TestClient fixtures (grep `backend/tests/conftest.py`); do NOT hand-roll `create_engine("sqlite://")` where a shared fixture exists.
- Inject platform + probe via a seam: `macos_contacts.configure(fake_snapshot=..., platform=...)` / monkeypatch `read_snapshot`/`probe_access`. A global autouse fixture **disables real Contacts probing + background sync** unless a test opts in.
- Temp photo roots (`tmp_path`) in every photo test.
- Add a test proving a **remote DSN is accepted** (and **remove** any remote-DSN-refusal test).
- Extend the canonical Alembic migration test + `ALL_TABLES` for `people`, `person_handle`, `contacts_sync_state` (columns, indexes, constraints, upgrade+downgrade).
- Update the exact connector-order/status tests with deterministic FDA probes.
- Retain a **manual, signed-package** macOS acceptance test (FDA responsible-process attribution, System Settings deep link, live-WAL read, photo storage) — cannot run in `tauri dev` or CI.

---

## Task 1 — Identity canonicalization (`identity.py`)

Pure module — no macOS, no DB, no `settings` at import time. This is the foundation the store's handle index and `resolve_handle` are built on, so its correctness gates everything downstream: a handle must canonicalize to ONE stable key regardless of how it was typed, and it must canonicalize the SAME way every time for the SAME region. The region is an **explicit argument** — callers pass the **persisted** `contacts_sync_state.normalization_region` (see the contract's *Region persistence*), never live `settings` at query time, so a later locale change can't silently re-key existing handles.

**Files:**
- Create: `backend/app/identity.py`
- Create: `backend/tests/test_identity.py`
- Modify: `backend/requirements.txt` (add `phonenumberslite`)

**Interfaces:**
- Consumes: `phonenumberslite` (imported as `phonenumbers`; pure-Python, offline, vendored via `scripts/vendor-python.sh`).
- Produces:
  - `canon_email(raw: str) -> str` — NFC + trim + lowercase; never raises; NOT a validator.
  - `canon_phone(raw: str, region: str) -> dict | None` — `region` is ISO-3166 alpha-2 (the persisted normalization region).
  - `canon_handle(raw: str, region: str) -> dict | None` — dispatches email-vs-phone.
  - The returned dict shape is exactly `{"normalized": str, "kind": "phone" | "email" | "short", "possible": bool}`; `None` means "not a keyable handle" (empty/whitespace-only input).

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:
```
phonenumberslite
```
Then install into the dev venv: `cd backend && .venv/bin/python -m pip install phonenumberslite`

- [ ] **Step 2: Write the failing test** — `backend/tests/test_identity.py`

This is the full brief §5 matrix: international vs national parsing, extensions, malformed input, region **changes** (same raw digits → different key under a different region), unicode + malformed emails, whitespace-only handles, duplicate entries collapsing, and shared-handle determinism.

```python
from app.identity import canon_email, canon_handle, canon_phone


# ---- phones: national variants collapse to one E.164 key ----------------------
def test_phone_national_variants_collapse_to_one_e164_key():
    for raw in ["+15551234567", "5551234567", "(555) 123-4567",
                "1-555-123-4567", "555.123.4567", " 555 123 4567 "]:
        assert canon_phone(raw, "US")["normalized"] == "+15551234567"


def test_duplicate_phone_spellings_produce_one_key():
    # A person listing the same number twice, formatted differently, indexes once.
    keys = {canon_phone(r, "US")["normalized"]
            for r in ["(555) 123-4567", "555-123-4567", "+1 555 123 4567"]}
    assert keys == {"+15551234567"}


def test_phone_keyed_even_when_not_strictly_valid():
    # 555 test range: "possible" but not "valid" — we must still key it, not drop it.
    r = canon_phone("5551234567", "US")
    assert r["normalized"] == "+15551234567"
    assert r["kind"] == "phone"
    assert r["possible"] is True


# ---- international vs national: '+' carries the country code, region is a fallback
def test_plus_prefixed_ignores_region_but_national_needs_it():
    # With a leading '+', the country code wins and the region argument is irrelevant.
    assert canon_phone("+442083661177", "US")["normalized"] == "+442083661177"
    # The SAME subscriber number in national form only resolves with the right region.
    assert canon_phone("020 8366 1177", "GB")["normalized"] == "+442083661177"


# ---- region CHANGE: identical raw digits canonicalize differently per region ---
def test_same_raw_number_canonicalizes_differently_under_different_regions():
    us = canon_phone("2025550173", "US")
    gb = canon_phone("2025550173", "GB")
    assert us["normalized"] == "+12025550173"          # +1 (NANP)
    assert gb["normalized"] == "+442025550173"         # +44 (GB)
    assert us["normalized"] != gb["normalized"]         # region is load-bearing


def test_region_change_does_not_reinterpret_as_us():
    # Prove a national GB number is NOT force-parsed as if it were US.
    gb = canon_phone("020 8366 1177", "GB")["normalized"]
    us = canon_phone("020 8366 1177", "US")
    assert gb == "+442083661177"
    assert us is None or us["normalized"] != gb


# ---- extensions & malformed numbers -------------------------------------------
def test_extension_is_stripped_from_the_e164_key():
    # E.164 has no extension; the same subscriber number keys once, ext and all.
    assert canon_phone("(555) 123-4567 ext. 890", "US")["normalized"] == "+15551234567"
    assert canon_phone("5551234567x123", "US")["normalized"] == "+15551234567"


def test_short_code():
    r = canon_phone("611", "US")
    assert r["kind"] == "short"
    assert r["normalized"] == "short:611"
    assert r["possible"] is False


def test_unparseable_phone_falls_back_to_digits_or_none():
    # Garbage with no digits is not keyable.
    assert canon_phone("not a phone", "US") is None
    assert canon_phone("", "US") is None
    assert canon_phone("   ", "US") is None
    # Malformed input that phonenumbers rejects but that still carries digits
    # keeps the raw digits so it can be matched later (never silently dropped).
    r = canon_phone("#$%1234%$#", "US")
    assert r is not None and r["kind"] == "phone" and r["possible"] is False
    assert r["normalized"] == "1234"


# ---- emails: NFC + trim + lowercase, NO gmail dot/plus folding -----------------
def test_email_lowercased_trimmed_no_dot_folding():
    assert canon_email("  Foo@iCloud.com ") == "foo@icloud.com"
    # Dots are significant everywhere except gmail — do NOT strip them.
    assert canon_email("f.o.o@icloud.com") == "f.o.o@icloud.com"
    # '+tag' is significant on non-gmail domains — do NOT strip it.
    assert canon_email("Jane+news@fastmail.com") == "jane+news@fastmail.com"


def test_email_unicode_is_nfc_normalized():
    # Build the two byte-distinct spellings explicitly (\u escapes) so the
    # test proves NFC folding rather than however the file encodes "é".
    decomposed = "cafe\u0301@example.com"   # e + U+0301 combining acute
    composed = "caf\u00e9@example.com"       # single precomposed \u00e9
    assert decomposed != composed             # genuinely different byte strings
    assert canon_email(decomposed) == canon_email(composed)  # both fold to one key


def test_email_is_not_a_validator_and_never_raises():
    # canon_email normalizes; it does not judge. Malformed input must not crash.
    assert canon_email("@@@") == "@@@"
    assert canon_email("") == ""
    assert canon_email("   ") == ""


# ---- canon_handle dispatch + whitespace-only -> None --------------------------
def test_canon_handle_dispatch():
    assert canon_handle("foo@icloud.com", "US")["kind"] == "email"
    assert canon_handle("+15551234567", "US")["kind"] == "phone"
    assert canon_handle("611", "US")["kind"] == "short"


def test_canon_handle_whitespace_only_is_none():
    assert canon_handle("", "US") is None
    assert canon_handle("   ", "US") is None
    assert canon_handle("\t\n ", "US") is None


def test_canon_handle_is_pure_and_shared_handle_is_deterministic():
    # Two different people carrying the SAME handle must produce IDENTICAL keys so
    # resolve_handle later maps both to one normalized value.
    a = canon_handle("Shared@iCloud.com", "US")
    b = canon_handle("shared@icloud.com", "US")
    assert a == b                                   # same key for both people
    assert canon_handle("+1 (555) 000-1111", "US") == canon_handle("5550001111", "US")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_identity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.identity'`

- [ ] **Step 4: Write the implementation** — `backend/app/identity.py`

```python
"""Canonicalize phone numbers and emails to a stable key for identity matching.

A single handle ("+15551234567", "5551234567", "Foo@iCloud.com") must collapse
to ONE key so an inbound message handle resolves to the right contact, and it
must collapse the SAME way every time for the same region.

- Phones go to E.164 via phonenumberslite (pure-Python, offline). The key is
  stored REGARDLESS of validity: gating on is_valid_number() silently drops
  legitimate test/MVNO/short ranges. `region` is the persisted normalization
  region (contract: Region persistence) — a leading '+' overrides it, a bare
  national number depends on it, so the same raw digits key differently under
  different regions. Extensions are dropped (E.164 carries none).
- Emails are NFC + trim + lowercase only. We deliberately do NOT apply Gmail
  dot/plus folding: that is a gmail.com-only rule and would false-merge distinct
  iCloud/custom-domain addresses. canon_email is a normalizer, not a validator.
"""
from __future__ import annotations

import re
import unicodedata

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, shortnumberinfo


def canon_email(raw: str) -> str:
    return unicodedata.normalize("NFC", raw or "").strip().lower()


def canon_phone(raw: str, region: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        n = phonenumbers.parse(raw, region)
    except NumberParseException:
        digits = re.sub(r"\D", "", raw)
        return {"normalized": digits, "kind": "phone", "possible": False} if digits else None
    if shortnumberinfo.is_valid_short_number(n):
        return {"normalized": f"short:{n.national_number}", "kind": "short", "possible": False}
    e164 = phonenumbers.format_number(n, PhoneNumberFormat.E164)
    return {"normalized": e164, "kind": "phone", "possible": phonenumbers.is_possible_number(n)}


def canon_handle(raw: str, region: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if "@" in raw:
        value = canon_email(raw)
        return {"normalized": value, "kind": "email", "possible": True} if value else None
    return canon_phone(raw, region)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_identity.py -q`
Expected: PASS (15)

- [ ] **Step 6: Run the full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` (report the count; baseline is **703 collected**, so expect **718** after this task)
```bash
git add backend/app/identity.py backend/tests/test_identity.py backend/requirements.txt
git commit -m "feat(people): phone/email canonicalization via phonenumberslite, explicit region (M10 s1)"
```

---

## Task 2 — Models + 0010 migration + `contacts_sync_state`

Three tables land together in one migration: `people` (the source-aware contact directory), `person_handle` (the normalized handle → person index that backs `resolve_handle`), and `contacts_sync_state` (the one-row-per-owner consent + lifecycle record from the contract's *Consent & lifecycle* section). The persisted photo reference is the opaque, **relative** `photo_key` (contract: *Photo storage*) — the reader's transient absolute path is converted to `photo_key` by the store, never persisted raw. `source_id` is the **already-hashed, namespaced** id the reader produces (contract: *Source ID namespacing*); the model just stores it as `String(128)`.

**Files:**
- Modify: `backend/app/models.py` (append after the last class)
- Create: `backend/alembic/versions/0010_people.py`
- Create: `backend/tests/test_migrations_people.py`
- Modify: `backend/tests/test_migrations.py` (extend `ALL_TABLES` + column assertions)

**Interfaces:**
- Consumes: `Base`, `JSONField`, `utcnow`, and the already-imported `String`, `Text`, `Boolean`, `DateTime`, `ForeignKey`, `UniqueConstraint`, `Mapped`, `mapped_column` from `backend/app/models.py`.
- Produces:
  - ORM `Person` (table `people`), `PersonHandle` (table `person_handle`), `ContactsSyncState` (table `contacts_sync_state`) registered on `Base.metadata` with the exact columns Tasks 3–5 read/write.
  - Migration `0010_people.py` with `revision = "0010"`, `down_revision = "0009"`, creating all three tables (indexes + constraints) with a reverse-order `downgrade()`.

- [ ] **Step 1: Write the failing metadata test** — `backend/tests/test_migrations_people.py`

```python
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401  — register tables on Base.metadata
from app.db import Base


def test_all_three_tables_exist_on_metadata():
    names = set(Base.metadata.tables)
    assert {"people", "person_handle", "contacts_sync_state"} <= names


def test_people_columns():
    cols = {c.name for c in Base.metadata.tables["people"].columns}
    assert {
        "owner", "source", "source_id", "display_name", "first_name",
        "last_name", "nickname", "organization", "job_title", "phones",
        "emails", "photo_key", "has_photo", "relationship",
        "relationship_strength", "notes", "pinned", "last_contacted_at",
        "removed_from_source_at", "meta", "created_at", "updated_at",
    } <= cols


def test_person_handle_columns():
    cols = {c.name for c in Base.metadata.tables["person_handle"].columns}
    assert {"owner", "person_id", "kind", "value", "possible", "created_at"} <= cols


def test_contacts_sync_state_columns():
    cols = {c.name for c in Base.metadata.tables["contacts_sync_state"].columns}
    assert {
        "owner", "enabled", "status", "access", "normalization_region",
        "last_sync_at", "last_error", "enabled_at", "created_at", "updated_at",
    } <= cols


def test_contacts_sync_state_owner_is_unique():
    table = Base.metadata.tables["contacts_sync_state"]
    unique_cols = {tuple(c.name for c in con.columns)
                   for con in table.constraints
                   if con.__class__.__name__ == "UniqueConstraint"}
    assert ("owner",) in unique_cols


def test_enabled_defaults_off():
    # App consent is OFF until the user explicitly connects (contract).
    col = Base.metadata.tables["contacts_sync_state"].columns["enabled"]
    assert col.default.arg is False


def test_create_all_builds_all_three_on_sqlite():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    tables = set(inspect(eng).get_table_names())
    assert {"people", "person_handle", "contacts_sync_state"} <= tables
    eng.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_migrations_people.py -q`
Expected: FAIL — `assert {'people', 'person_handle', 'contacts_sync_state'} <= names` (the tables aren't on `Base.metadata` yet).

- [ ] **Step 3: Add the ORM models** — append to `backend/app/models.py` (after the final class; `String`, `Text`, `Boolean`, `DateTime`, `ForeignKey`, `UniqueConstraint`, `JSONField`, `utcnow`, `datetime`, `Mapped`, `mapped_column` are already imported at the top of the file)

```python
class Person(Base):
    """A contact (M10 s1). `source='macos_contacts'` rows are synced one-way from
    the local AddressBook and keyed (owner, source, source_id) for idempotent
    upsert; `source='manual'` rows are user-created. source_id is the already-
    hashed, namespaced id from the reader (contract: Source ID namespacing) — the
    model just stores it.

    Ownership split (contract: Sync-owned vs CRM-native): sync writes ONLY the
    sync-owned identity fields (names, org, phones/emails, photo_key/has_photo,
    meta); the CRM-native block (relationship .. last_contacted_at) is
    ScuffedOS-owned and never touched by sync. `removed_from_source_at`
    soft-deletes a contact that vanished from AddressBook (preserving its CRM
    data) and is cleared on any re-upsert (resurrection).

    Photos: `photo_key` is the opaque, RELATIVE key persisted here (contract:
    Photo storage); the extracted bytes live on the backend host's App Support
    filesystem, never in this table."""

    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_people_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'macos_contacts' | 'manual'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # hashed, namespaced (reader)
    display_name: Mapped[str] = mapped_column(Text, default="")
    first_name: Mapped[str] = mapped_column(Text, default="")
    last_name: Mapped[str] = mapped_column(Text, default="")
    nickname: Mapped[str] = mapped_column(Text, default="")
    organization: Mapped[str] = mapped_column(Text, default="")
    job_title: Mapped[str] = mapped_column(Text, default="")
    phones: Mapped[list] = mapped_column(JSONField, default=list)      # [{value, label, normalized}]
    emails: Mapped[list] = mapped_column(JSONField, default=list)      # [{value, label, normalized}]
    photo_key: Mapped[str | None] = mapped_column(Text)               # opaque, RELATIVE (contract)
    has_photo: Mapped[bool] = mapped_column(default=False)
    # ---- CRM-native (ScuffedOS-owned; sync NEVER writes these) ----
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
    """Normalized handle -> person index for resolve_handle (M10 s1). One row per
    (person_id, kind, value); `value` is the canonical key from app.identity and
    `kind` is 'phone' | 'email' | 'short'. Kept across soft-delete so historical
    messages still resolve to a removed contact. A single handle may map to many
    people (shared family/household numbers) -> resolve_handle returns a list."""

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
    kind: Mapped[str] = mapped_column(String(16))               # 'phone' | 'email' | 'short'
    value: Mapped[str] = mapped_column(String(320), index=True)  # normalized key
    possible: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContactsSyncState(Base):
    """One row per owner: the Contacts connector's consent + lifecycle record
    (contract: Consent & lifecycle). `enabled` is APP CONSENT and defaults OFF —
    no probing, no background sync, and no reads happen until the user explicitly
    connects. `access` (FDA state) is tracked SEPARATELY from consent.
    `normalization_region` is the region persisted at enable/first-sync used to
    canonicalize handles; a later system-locale change does NOT retroactively
    alter it (contract: Region persistence)."""

    __tablename__ = "contacts_sync_state"
    __table_args__ = (
        UniqueConstraint("owner", name="uq_contacts_sync_state_owner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))              # unique via constraint above
    # app consent (default OFF); status/access are independent
    enabled: Mapped[bool] = mapped_column(default=False)
    # 'disabled' | 'access_denied' | 'ready' | 'syncing' | 'stale' | 'error'
    status: Mapped[str] = mapped_column(String(16), default="disabled")
    # 'granted' | 'denied' | 'unknown'
    access: Mapped[str] = mapped_column(String(16), default="unknown")
    normalization_region: Mapped[str | None] = mapped_column(String(8))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
```

- [ ] **Step 4: Run the metadata test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_migrations_people.py -q`
Expected: PASS (7). The models are now on `Base.metadata` and `create_all` builds all three on SQLite.

- [ ] **Step 5: Extend the canonical Alembic migration test** — `backend/tests/test_migrations.py`

Add the three new tables to `ALL_TABLES` (so `test_upgrade_head_builds_full_schema` requires the real migration to build them, and `test_downgrade_base_removes_everything` requires the downgrade to drop them):
```python
ALL_TABLES = {
    "tasks", "memories", "conversations", "conversation_messages",
    "task_reminders", "events", "habits", "habit_completions",
    "meals", "water_days", "nutrition_targets",
    "provider_accounts", "daily_snapshots", "workouts", "emails",
    "moodle_courses", "moodle_deadlines", "moodle_assignments",
    "moodle_grades", "moodle_announcements", "moodle_notifications",
    "finance_items", "finance_accounts", "finance_transactions",
    "finance_securities", "finance_holdings", "finance_budgets",
    "finance_recurring", "finance_liabilities", "finance_investment_transactions",
    "people", "person_handle", "contacts_sync_state",
}
```
Then, inside `test_upgrade_head_builds_full_schema`, append these column assertions just before `engine.dispose()`:
```python
    people_cols = {c["name"] for c in inspect(engine).get_columns("people")}
    assert {"owner", "source", "source_id", "display_name", "first_name",
            "last_name", "nickname", "organization", "job_title", "phones",
            "emails", "photo_key", "has_photo", "relationship",
            "relationship_strength", "notes", "pinned", "last_contacted_at",
            "removed_from_source_at", "meta", "created_at", "updated_at"} <= people_cols

    handle_cols = {c["name"] for c in inspect(engine).get_columns("person_handle")}
    assert {"owner", "person_id", "kind", "value", "possible", "created_at"} <= handle_cols

    state_cols = {c["name"] for c in inspect(engine).get_columns("contacts_sync_state")}
    assert {"owner", "enabled", "status", "access", "normalization_region",
            "last_sync_at", "last_error", "enabled_at",
            "created_at", "updated_at"} <= state_cols
```

Run: `cd backend && .venv/bin/python -m pytest tests/test_migrations.py -q`
Expected: FAIL — `test_upgrade_head_builds_full_schema` errors because `0010` doesn't exist yet, so `alembic upgrade head` never creates `people`/`person_handle`/`contacts_sync_state`.

- [ ] **Step 6: Write the migration** — `backend/alembic/versions/0010_people.py`

Mirrors the finance-slice idiom (`0009`): `JSONField` variant, `op.f("ix_…")` index names, table-level `UniqueConstraint`, reverse-order `downgrade()`.

```python
"""People domain (M10 s1): source-aware contacts directory + handle index +
Contacts connector consent/lifecycle state.

Creates three tables:
  * people               — contacts keyed (owner, source, source_id)
  * person_handle        — normalized handle -> person index (resolve_handle)
  * contacts_sync_state  — one row per owner; app consent (enabled, default off)
                           tracked separately from FDA access + normalization_region

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
        sa.Column("photo_key", sa.Text(), nullable=True),
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

    op.create_table(
        "contacts_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("access", sa.String(length=16), nullable=False),
        sa.Column("normalization_region", sa.String(length=8), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", name="uq_contacts_sync_state_owner"),
    )


def downgrade() -> None:
    op.drop_table("contacts_sync_state")
    op.drop_table("person_handle")
    op.drop_table("people")
```

- [ ] **Step 7: Run the migration tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_migrations.py tests/test_migrations_people.py -q`
Expected: PASS — `test_upgrade_head_builds_full_schema` now finds all three tables + their columns, and `test_downgrade_base_removes_everything` confirms the reverse-order downgrade drops them.

- [ ] **Step 8: Verify the migration applies both directions on dev Postgres** (needs dev PG; skip and note if unavailable)

Run: `cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: no errors; head reports `0010`. If a `TEST_DATABASE_URL` Postgres is configured, also run `cd backend && TEST_DATABASE_URL=$TEST_DATABASE_URL .venv/bin/python -m pytest tests/test_migrations.py::test_migrations_build_models_schema_on_postgres -q` — `compare_metadata` must report **no drift** between the three new models and the `0010` migration.

- [ ] **Step 9: Full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` (report the count; expect **+7** over Task 1 — the 7 new tests in `test_migrations_people.py`; the `test_migrations.py` edits extend assertions inside existing tests, adding no new test items — so ~**725** collected)
```bash
git add backend/app/models.py backend/alembic/versions/0010_people.py backend/tests/test_migrations_people.py backend/tests/test_migrations.py
git commit -m "feat(people): Person + PersonHandle + contacts_sync_state models + 0010 migration (M10 s1)"
```

---

---

## Task 3: Store — transactional snapshot apply + handle index + source-aware CRUD + locking

The heart of the slice. Everything the reader (Task 4) produces flows through
`store.apply_contacts_snapshot(snapshot, now) -> SyncResult`: **one** DB
transaction — held under a module process lock **and** (on PostgreSQL) a
transaction-scoped advisory lock — that upserts every person, rebuilds each
person's handle index, and reconciles soft-deletions, but *only* when the read
was genuinely complete and clean. A non-complete snapshot records state and
writes **no** rows; an `ACCESS_DENIED` read with existing rows marks the sync
state `stale` and never soft-deletes. Structured contact fields persist to the
configured PostgreSQL database (which may run locally or on a remote/self-hosted
server); a soft-delete preserves the row (and its CRM-native data) so the
handle index still resolves historical messages.

This task also lands the source-aware CRUD (`create/update/delete/get/list`
person), `resolve_handle -> list[dict]`, and the consent-state get/set helpers,
plus the idempotency fix: normalized phone/email values are written as **fresh
dict copies reassigned to the JSON column** — never mutated in place after a
flush — so `normalized` actually persists across sessions.

> **Shared-type coordination.** This task creates the three sync-contract value
> types the later tasks import: `SnapshotStatus`, `ContactsSnapshot`, and
> `SyncResult` live in `backend/app/providers/macos_contacts.py` (types only —
> **Task 4 appends its reader beneath them and must not redefine them**);
> `NormalizedPerson` lives in `backend/app/providers/base.py`. Task 4's reader
> imports `NormalizedPerson`; Task 5's engine calls `apply_contacts_snapshot`
> and imports `SyncResult`.

**Files:**
- Modify: `backend/app/providers/base.py` (add `NormalizedPerson`)
- Create: `backend/app/providers/macos_contacts.py` (shared snapshot/sync value types only; Task 4 appends the reader)
- Modify: `backend/app/config.py` (add `contacts_default_region`; Task 5 upgrades its default to `_default_region()`)
- Modify: `backend/app/store.py` (imports, module helpers, `# ---- people (M10) ----` methods)
- Create: `backend/tests/test_people_store.py`

**Interfaces:**
- Consumes:
  - `Person`, `PersonHandle`, `ContactsSyncState` ORM models (Task 2), columns exactly as in the contract (`people`.`photo_key`, `people`.`removed_from_source_at`, `contacts_sync_state`.`normalization_region`/`enabled`/`status`/`access`/`enabled_at`/`last_sync_at`/`last_error`).
  - `canon_handle(raw: str, default_region: str) -> dict | None` (Task 1) → `{"normalized","kind","possible"}`.
  - `settings.owner` (`"me"`), `settings.contacts_default_region` (added here).
- Produces (exact signatures):
  - `SnapshotStatus`, `ContactsSnapshot`, `SyncResult` (contract §Design Contract), `NormalizedPerson`.
  - `store.apply_contacts_snapshot(snapshot: ContactsSnapshot, now: datetime) -> SyncResult`
  - `store.upsert_person(person: NormalizedPerson) -> dict`
  - `store.resolve_handle(handle: str) -> list[dict]`
  - `store.list_people(*, include_removed: bool = False, q: str | None = None, limit: int = 50, cursor: str | None = None) -> dict` → `{"items": list[dict], "next_cursor": str | None}`
  - `store.get_person(person_id: int) -> dict | None`
  - `store.create_person(data: dict) -> dict`
  - `store.update_person(person_id: int, patch: dict) -> dict | None`
  - `store.delete_person(person_id: int) -> bool`
  - `store.get_contacts_state() -> dict`; `store.set_contacts_state(patch: dict) -> dict`; `store.set_contacts_enabled(enabled: bool, *, region: str | None = None, now: datetime | None = None) -> dict` (thin consent toggle over `set_contacts_state`; Task 10 tests call this)
  - module `_person_dict(p) -> dict`, `_state_dict(st) -> dict`
  - module `_encode_cursor(display_name, id) -> str` / `_decode_cursor(token) -> tuple[str|None, int|None]` (the single keyset-cursor codec; Task 7's router reuses it)

- [ ] **Step 1: Add the shared value types + config region**

Append `NormalizedPerson` to `backend/app/providers/base.py` (near the other `Normalized*` dataclasses; `dataclass`, `field` are already imported):
```python
@dataclass
class NormalizedPerson:
    """A contact as produced by the local macOS AddressBook reader (Task 4).
    phones/emails arrive as ``[{"value","label"}]``; the store fills ``normalized``
    from ``app.identity``. ``photo_path`` is the reader's TRANSIENT absolute path to
    the extracted file on the backend host; the store converts it to the opaque,
    relative ``photo_key`` it persists (contract: Photo storage)."""

    source: str                                  # 'macos_contacts'
    source_id: str
    display_name: str
    first_name: str = ""
    last_name: str = ""
    nickname: str = ""
    organization: str = ""
    job_title: str = ""
    phones: list = field(default_factory=list)   # [{value, label}]
    emails: list = field(default_factory=list)   # [{value, label}]
    photo_path: str | None = None                # transient absolute path; store -> photo_key
    has_photo: bool = False
    meta: dict = field(default_factory=dict)
```

Create `backend/app/providers/macos_contacts.py` with **only** the shared types
(Task 4 appends its reader below and imports `NormalizedPerson` from `.base`):
```python
"""macOS Contacts source-of-truth module (M10 s1).

This file lands ONLY the shared sync-contract value types below. Task 4 APPENDS
the local, read-only AddressBook reader (``read_snapshot``, ``probe_access``,
``DEFAULT_ROOT``, photo extraction) beneath them — it imports ``NormalizedPerson``
from ``.base`` and must NOT redefine these types.

Contacts are read locally and read-only from the machine running the backend;
the structured fields persist to the configured PostgreSQL database, which may
run locally (loopback) or on a remote/self-hosted server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SnapshotStatus(str, Enum):
    COMPLETE_NONEMPTY = "complete_nonempty"   # all discovered stores read OK; >=1 contact
    COMPLETE_EMPTY = "complete_empty"         # all discovered stores read OK; zero contacts
    ACCESS_DENIED = "access_denied"           # EPERM / Full Disk Access missing
    UNSUPPORTED_SCHEMA = "unsupported_schema" # missing ABCDContact entity or required table/column
    MISSING_STORE = "missing_store"           # no AddressBook store files present
    PARTIAL_READ = "partial_read"             # >=1 store read but >=1 failed -> reconciliation unsafe
    IO_ERROR = "io_error"                     # sqlite corruption / generic I/O failure


@dataclass
class ContactsSnapshot:
    status: SnapshotStatus
    people: list                              # list[NormalizedPerson]; populated only for COMPLETE_*
    stores_total: int = 0
    stores_read: int = 0
    store_ids: list = field(default_factory=list)   # stable ids of stores read OK
    error: str | None = None                  # redacted; never a DSN/credential


@dataclass
class SyncResult:
    status: str          # 'ok' | 'empty' | 'access_denied' | 'unsupported' | 'partial' | 'error' | 'disabled'
    access: str          # 'granted' | 'denied' | 'unknown'
    imported: int = 0
    updated: int = 0
    removed: int = 0
    last_sync_at: object | None = None   # datetime
    last_error: str | None = None
```

Add the region setting to `backend/app/config.py`, in the `Settings` body after
the finance-sync block (`plaid_backfill_days`):
```python
    # ---- M10 Contacts (local macOS AddressBook) ----
    # ISO-3166 alpha-2 fallback for E.164 normalization when contacts_sync_state
    # has not yet persisted a normalization_region. Task 5 upgrades the default
    # to _default_region() (system-locale sniff); "US" keeps Task 3 self-contained.
    contacts_default_region: str = "US"
    # Background contacts sync loop: armed only when True (per-tick consent is a
    # SEPARATE gate via contacts_sync_state.enabled). Defaults OFF (consent-gated).
    contacts_sync_enabled: bool = False
    contacts_sync_seconds: int = 21600           # 6h between background passes
    # Contact-photo store dir: relative -> resolved UNDER app_support_dir (never
    # ./data); absolute kept as-is. Resolved via contacts_photos_root().
    contacts_photos_dir: str = "contact_photos"

    def contacts_photos_root(self) -> str:
        """Absolute contact-photos root (App Support + contacts_photos_dir). The
        import is function-local to avoid a config <-> providers import cycle."""
        from .providers import contact_photos

        return contact_photos.resolve_root(self)
```

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_people_store.py`

Reuses the repo's shared autouse `fresh_db` fixture (grep `backend/tests/conftest.py`)
— it binds the `store` singleton to a clean schema per test, so these tests only
touch `store`.
```python
from datetime import datetime, timezone

import pytest

from app.providers.base import NormalizedPerson
from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus, SyncResult
from app.store import store

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _np(**kw):
    kw.setdefault("source", "macos_contacts")
    kw.setdefault("source_id", "A")
    kw.setdefault("display_name", kw["source_id"])
    return NormalizedPerson(**kw)


def _snap(people, status=SnapshotStatus.COMPLETE_NONEMPTY, **kw):
    return ContactsSnapshot(status=status, people=list(people),
                            stores_total=1, stores_read=1, store_ids=["local"], **kw)


# ---- apply_contacts_snapshot: import, index, idempotency ----

def test_apply_imports_indexes_handles_and_persists_normalized():
    p = _np(source_id="A", display_name="Jane Doe",
            phones=[{"value": "(555) 123-4567", "label": "Mobile"}],
            emails=[{"value": "Jane@iCloud.com", "label": "Home"}])
    res = store.apply_contacts_snapshot(_snap([p]), NOW)
    assert isinstance(res, SyncResult)
    assert res.status == "ok" and res.access == "granted"
    assert (res.imported, res.updated, res.removed) == (1, 0, 0)
    # A FRESH-SESSION read proves normalized landed in the JSON column (not just
    # mutated on an in-memory dict that never got flushed).
    items = store.list_people()["items"]
    assert len(items) == 1
    assert items[0]["phones"][0]["normalized"] == "+15551234567"
    assert items[0]["phones"][0]["label"] == "Mobile"
    assert items[0]["emails"][0]["normalized"] == "jane@icloud.com"
    # The handle index resolves both a phone spelling and the email to the person.
    assert [h["id"] for h in store.resolve_handle("+1 (555) 123-4567")] == [items[0]["id"]]
    assert store.resolve_handle("jane@icloud.com")[0]["id"] == items[0]["id"]


def test_apply_is_idempotent_and_updates_in_place():
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Jane")]), NOW)
    res = store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Jane D.")]), NOW)
    assert (res.imported, res.updated) == (0, 1)
    items = store.list_people()["items"]
    assert len(items) == 1
    assert items[0]["display_name"] == "Jane D."


def test_authoritative_snapshot_without_handles_removes_them():
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Jane",
        phones=[{"value": "+15551234567", "label": "Mobile"}])]), NOW)
    assert store.resolve_handle("+15551234567")
    # A later COMPLETE snapshot that omits the phone must DROP the handle + JSON entry.
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Jane")]), NOW)
    assert store.resolve_handle("+15551234567") == []
    assert store.list_people()["items"][0]["phones"] == []


# ---- reconciliation: soft-delete + resurrection + empty source ----

def test_reconcile_soft_deletes_missing_then_resurrects():
    store.apply_contacts_snapshot(_snap([_np(source_id="A"), _np(source_id="B")]), NOW)
    res = store.apply_contacts_snapshot(_snap([_np(source_id="A")]), NOW)
    assert res.removed == 1
    assert {p["source_id"] for p in store.list_people()["items"]} == {"A"}
    assert len(store.list_people(include_removed=True)["items"]) == 2
    # B returns in a later snapshot -> resurrected (removed_from_source_at cleared).
    store.apply_contacts_snapshot(_snap([_np(source_id="A"), _np(source_id="B")]), NOW)
    assert {p["source_id"] for p in store.list_people()["items"]} == {"A", "B"}


def test_complete_empty_snapshot_soft_deletes_all():
    store.apply_contacts_snapshot(_snap([_np(source_id="A"), _np(source_id="B")]), NOW)
    res = store.apply_contacts_snapshot(_snap([], status=SnapshotStatus.COMPLETE_EMPTY), NOW)
    assert res.status == "empty" and res.removed == 2
    assert store.list_people()["items"] == []
    assert store.get_contacts_state()["status"] == "ready"


# ---- non-complete reads never write rows / never soft-delete ----

def test_access_denied_with_existing_rows_marks_stale_never_deletes():
    store.apply_contacts_snapshot(_snap([_np(source_id="A"), _np(source_id="B")]), NOW)
    res = store.apply_contacts_snapshot(
        ContactsSnapshot(status=SnapshotStatus.ACCESS_DENIED, people=[], error="FDA denied"), NOW)
    assert res.status == "access_denied" and res.access == "denied" and res.removed == 0
    assert len(store.list_people()["items"]) == 2            # nothing hidden
    assert store.get_contacts_state()["status"] == "stale"


def test_access_denied_with_no_rows_sets_access_denied_status():
    res = store.apply_contacts_snapshot(
        ContactsSnapshot(status=SnapshotStatus.ACCESS_DENIED, people=[], error="no FDA"), NOW)
    assert res.status == "access_denied"
    st = store.get_contacts_state()
    assert st["status"] == "access_denied" and st["access"] == "denied"


@pytest.mark.parametrize("status,expected", [
    (SnapshotStatus.UNSUPPORTED_SCHEMA, "unsupported"),
    (SnapshotStatus.MISSING_STORE, "error"),
    (SnapshotStatus.PARTIAL_READ, "partial"),
    (SnapshotStatus.IO_ERROR, "error"),
])
def test_non_complete_reads_keep_rows(status, expected):
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Keep")]), NOW)
    res = store.apply_contacts_snapshot(
        ContactsSnapshot(status=status, people=[], error="x"), NOW)
    assert res.status == expected and res.removed == 0
    assert [p["display_name"] for p in store.list_people()["items"]] == ["Keep"]


def test_partial_apply_commits_good_rows_and_skips_reconcile():
    store.apply_contacts_snapshot(_snap([_np(source_id="C", display_name="Carol")]), NOW)
    good = _np(source_id="G", display_name="Good",
               emails=[{"value": "g@x.com", "label": "Home"}])
    bad = _np(source_id="BAD", display_name="Bad")
    bad.phones = 12345                       # not iterable -> raises inside the per-record savepoint
    res = store.apply_contacts_snapshot(_snap([good, bad]), NOW)
    assert res.status == "partial" and res.removed == 0     # reconcile skipped
    names = {p["display_name"] for p in store.list_people()["items"]}
    assert "Good" in names                                  # good row committed
    assert "Bad" not in names                               # bad row rolled back to savepoint
    assert "Carol" in names                                 # NOT soft-deleted (reconcile skipped)
    assert store.get_contacts_state()["status"] == "error"


# ---- source-aware CRUD ----

def test_manual_crud_and_imported_identity_is_read_only():
    m = store.create_person({"display_name": "Ada", "relationship": "Friend"})
    assert m["source"] == "manual"
    assert store.update_person(m["id"], {"display_name": "Ada L."})["display_name"] == "Ada L."
    # Imported rows: identity fields are server-enforced read-only; CRM-native editable.
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Imported Jane")]), NOW)
    imp = store.list_people(q="Imported")["items"][0]
    out = store.update_person(imp["id"], {"display_name": "HACKED", "relationship": "Family"})
    assert out["display_name"] == "Imported Jane"           # read-only held
    assert out["relationship"] == "Family"                  # CRM-native applied


def test_delete_hard_for_manual_soft_tombstone_for_imported():
    m = store.create_person({"display_name": "Manual"})
    assert store.delete_person(m["id"]) is True
    assert store.get_person(m["id"]) is None                # manual -> hard delete
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Imp",
        phones=[{"value": "+15550002222"}])]), NOW)
    imp = store.list_people(q="Imp")["items"][0]
    assert store.delete_person(imp["id"]) is True
    assert store.get_person(imp["id"])["removed_from_source_at"] is not None  # tombstoned, not gone
    assert store.list_people(q="Imp")["items"] == []                          # hidden from active list
    assert store.resolve_handle("+15550002222")[0]["id"] == imp["id"]         # still resolves (history)


def test_patch_null_semantics_never_500_and_blank_name_guarded():
    m = store.create_person({"display_name": "Nina", "relationship": "Friend", "notes": "hi"})
    assert store.update_person(m["id"], {"relationship": None})["relationship"] is None  # nullable cleared
    assert store.update_person(m["id"], {"display_name": None})["display_name"] == "Nina" # non-null null ignored
    assert store.update_person(m["id"], {"display_name": "   "})["display_name"] == "Nina" # blank ignored
    assert store.update_person(m["id"], {"bogus": 1, "notes": "bye"})["notes"] == "bye"    # unknown key ignored


def test_relationship_strength_is_bounded_1_to_5():
    m = store.create_person({"display_name": "Rex", "relationship_strength": 99})
    assert store.get_person(m["id"])["relationship_strength"] == 5
    store.update_person(m["id"], {"relationship_strength": 0})
    assert store.get_person(m["id"])["relationship_strength"] == 1


def test_create_person_rejects_whitespace_only_name():
    with pytest.raises(ValueError):
        store.create_person({"display_name": "   "})


# ---- resolve_handle: multi-match, dedupe, recency order, persisted region ----

def test_manual_edit_dedupes_and_removes_handles():
    p = store.create_person({"display_name": "Sam",
                             "phones": [{"value": "555-123-4567", "label": "Cell"},
                                        {"value": "+1 (555) 123-4567", "label": "Work"}]})
    assert store.resolve_handle("+15551234567")[0]["id"] == p["id"]   # two spellings -> one handle
    store.update_person(p["id"], {"phones": []})                      # authoritative empty replace
    assert store.resolve_handle("+15551234567") == []


def test_resolve_handle_returns_all_people_sharing_a_handle():
    a = store.create_person({"display_name": "Sue", "phones": [{"value": "+15550001111"}]})
    b = store.create_person({"display_name": "Bob", "phones": [{"value": "+15550001111"}]})
    assert {h["id"] for h in store.resolve_handle("+15550001111")} == {a["id"], b["id"]}


def test_resolve_handle_orders_by_recency_and_includes_soft_deleted():
    store.apply_contacts_snapshot(_snap([
        _np(source_id="OLD", display_name="Old", phones=[{"value": "+15559990000"}]),
        _np(source_id="NEW", display_name="Recent", phones=[{"value": "+15559990000"}]),
    ]), NOW)
    ids = {p["display_name"]: p["id"] for p in store.list_people()["items"]}
    # last_contacted_at is CRM-native and editable even on an imported row.
    store.update_person(ids["Recent"], {"last_contacted_at": datetime(2026, 7, 12, tzinfo=timezone.utc)})
    assert [h["display_name"] for h in store.resolve_handle("+1 555 999 0000")] == ["Recent", "Old"]
    # A later authoritative snapshot drops Recent -> soft-deleted but still resolves.
    store.apply_contacts_snapshot(_snap([
        _np(source_id="OLD", display_name="Old", phones=[{"value": "+15559990000"}]),
    ]), NOW)
    assert {h["display_name"] for h in store.resolve_handle("+15559990000")} == {"Recent", "Old"}


# ---- list_people: bounded search + deterministic cursor pagination ----

def test_list_people_search_and_cursor_pagination():
    for name in ["Alice", "Bob", "Carol", "Dave", "Erin"]:
        store.create_person({"display_name": name})
    store.create_person({"display_name": "Zoe", "organization": "Acme"})
    assert {p["display_name"] for p in store.list_people(q="acme")["items"]} == {"Zoe"}   # org searched
    assert {p["display_name"] for p in store.list_people(q="ar")["items"]} == {"Carol"}   # name substring
    page1 = store.list_people(limit=2)
    assert [p["display_name"] for p in page1["items"]] == ["Alice", "Bob"]
    assert page1["next_cursor"]
    page2 = store.list_people(limit=2, cursor=page1["next_cursor"])
    assert [p["display_name"] for p in page2["items"]] == ["Carol", "Dave"]
    page3 = store.list_people(limit=2, cursor=page2["next_cursor"])
    assert [p["display_name"] for p in page3["items"]] == ["Erin", "Zoe"]
    assert page3["next_cursor"] is None


# ---- consent state + persisted normalization region ----

def test_contacts_state_get_creates_default_and_set_patches():
    st = store.get_contacts_state()
    assert st["enabled"] is False
    out = store.set_contacts_state({
        "enabled": True, "status": "ready", "access": "granted",
        "normalization_region": "GB",
        "enabled_at": datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
    })
    assert out["enabled"] is True and out["normalization_region"] == "GB"
    assert out["enabled_at"].tzinfo is not None                     # stored UTC-aware
    # The PERSISTED region (GB), not the settings default (US), canonicalizes handles.
    p = store.create_person({"display_name": "Nigel", "phones": [{"value": "020 8366 1177"}]})
    assert store.resolve_handle("+442083661177")[0]["id"] == p["id"]
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_people_store.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'apply_contacts_snapshot'` (and no `NormalizedPerson`/`macos_contacts` types until Step 1 lands).

- [ ] **Step 4: Add store imports + module-level helpers** — `backend/app/store.py`

Widen the SQLAlchemy import and add the stdlib imports (near the top, with the
existing `import functools` / `import logging`):
```python
import base64
import functools
import hashlib
import json
import logging
import threading
from contextlib import contextmanager
```
```python
from sqlalchemy import and_, case, delete, func, or_, select, text
```
Add `Person`, `PersonHandle`, `ContactsSyncState` to the existing
`from .models import (...)` block, and `NormalizedPerson` to the existing
`from .providers.base import (...)` block. Then add one new import line for the
shared sync-contract types (Task 3 created them; Task 4 fills the reader in the
same module):
```python
from .providers.macos_contacts import ContactsSnapshot, SnapshotStatus, SyncResult
```

Add the module-level lock, advisory-key helper, cursor codec, field sets, clean
helpers, canonicalizer, and dict serializers (place them near the other
module-level `_*_dict` helpers, e.g. after `_email_dict`):
```python
# ---- people (M10): locking + helpers ----
# Serializes every contacts mutation within this process; on PostgreSQL a
# transaction-scoped advisory lock (below) extends that guarantee across
# processes/hosts sharing the database. RLock so a retried @_retry_integrity
# call on the same thread can't self-deadlock.
_CONTACTS_LOCK = threading.RLock()

# Non-COMPLETE snapshot -> (SyncResult.status, contacts_sync_state.status, access).
# ACCESS_DENIED is handled inline (stale vs access_denied depends on existing rows).
_FAILED_MAP = {
    SnapshotStatus.UNSUPPORTED_SCHEMA: ("unsupported", "error", "unknown"),
    SnapshotStatus.MISSING_STORE:      ("error", "error", "unknown"),
    SnapshotStatus.PARTIAL_READ:       ("partial", "stale", "unknown"),
    SnapshotStatus.IO_ERROR:           ("error", "error", "unknown"),
}

# Sync-owned identity fields: written by the snapshot apply; server-enforced
# READ-ONLY on imported rows via the CRUD patch path. CRM-native fields
# (relationship*/notes/pinned/last_contacted_at) are ScuffedOS-owned and editable.
_PERSON_NAME_FIELDS = ("display_name", "first_name", "last_name",
                       "nickname", "organization", "job_title")
_PERSON_SYNC_FIELDS = _PERSON_NAME_FIELDS + ("phones", "emails", "photo_key", "has_photo")
_PERSON_IMMUTABLE = ("id", "owner", "source", "source_id",
                     "created_at", "updated_at", "meta", "removed_from_source_at")


def _advisory_key(owner: str) -> int:
    """Stable signed 64-bit key for pg_advisory_xact_lock, namespaced per owner."""
    digest = hashlib.sha1(f"scuffedos:contacts_sync:{owner}".encode()).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def _encode_cursor(display_name: str, person_id: int) -> str:
    """Opaque keyset cursor = base64(JSON [display_name, id]). SINGLE definition
    for the whole store — list_people (Task 3) and the router's paginated list
    (Task 7) both reuse it; do NOT redefine it elsewhere."""
    raw = json.dumps([display_name, person_id]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str | None, int | None]:
    """Inverse of _encode_cursor; returns (None, None) on any malformed token so a
    bad cursor yields an empty/whole page instead of a 500."""
    try:
        name, person_id = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return name, int(person_id)
    except Exception:
        return None, None


def _clean_name(v, maxlen: int = 256) -> str:
    return str(v or "").strip()[:maxlen]


def _clean_label(v, maxlen: int = 64) -> str:
    return str(v or "").strip()[:maxlen]


def _clean_value(v, maxlen: int = 320) -> str:
    return str(v or "").strip()[:maxlen]


def _clean_strength(v) -> int | None:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return None


def _canon_entries(phones, emails, region: str):
    """Return (norm_phones, norm_emails, handles) as FRESH dicts/keys.

    Each stored entry is a brand-new ``{value,label,normalized}`` dict — reassigned
    wholesale to the JSON column by the caller so SQLAlchemy detects the change and
    ``normalized`` actually persists. ``handles`` maps a deduped ``(kind, value)``
    key to its ``possible`` flag for the PersonHandle rebuild. Never mutates the
    caller's input dicts.
    """
    from .identity import canon_handle

    norm_phones: list[dict] = []
    norm_emails: list[dict] = []
    handles: dict[tuple[str, str], bool] = {}
    for entries, out in ((phones, norm_phones), (emails, norm_emails)):
        for entry in entries or []:
            value = _clean_value((entry or {}).get("value", ""))
            if not value:
                continue
            label = _clean_label((entry or {}).get("label", ""))
            canon = canon_handle(value, region)
            out.append({"value": value, "label": label,
                        "normalized": canon["normalized"] if canon else None})
            if canon:
                handles.setdefault((canon["kind"], canon["normalized"]), canon["possible"])
    return norm_phones, norm_emails, handles


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
        "has_photo": bool(p.has_photo),
        "relationship": p.relationship,
        "relationship_strength": p.relationship_strength,
        "notes": p.notes,
        "pinned": bool(p.pinned),
        "last_contacted_at": aware_utc(p.last_contacted_at),
        "removed_from_source_at": aware_utc(p.removed_from_source_at),
        "created_at": aware_utc(p.created_at),
        "updated_at": aware_utc(p.updated_at),
    }


def _state_dict(st: ContactsSyncState) -> dict:
    return {
        "owner": st.owner,
        "enabled": bool(st.enabled),
        "status": st.status,
        "access": st.access,
        "normalization_region": st.normalization_region,
        "last_sync_at": aware_utc(st.last_sync_at),
        "last_error": st.last_error,
        "enabled_at": aware_utc(st.enabled_at),
        "created_at": aware_utc(st.created_at),
        "updated_at": aware_utc(st.updated_at),
    }
```

- [ ] **Step 5: Add the person + consent-state methods** — in class `Store`, after `get_email` (mark the block `# ---- people (M10) ----`)

```python
    # ---- people (M10) ----
    @contextmanager
    def _locked_write(self):
        """One serialized write transaction. Holds the module process lock and,
        on PostgreSQL, a transaction-scoped advisory lock so overlapping syncs /
        manual edits across processes or hosts can never interleave. SQLite (tests)
        -> the advisory lock is a no-op."""
        from .config import settings

        with _CONTACTS_LOCK:
            with self._session() as s, s.begin():
                if s.get_bind().dialect.name == "postgresql":
                    s.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                              {"k": _advisory_key(settings.owner)})
                yield s

    def _state_row(self, s: Session) -> ContactsSyncState:
        from .config import settings

        row = s.scalars(
            select(ContactsSyncState).where(ContactsSyncState.owner == settings.owner)
        ).first()
        if row is None:
            row = ContactsSyncState(owner=settings.owner)
            s.add(row)
            s.flush()
        return row

    def _person_row(self, s: Session, source: str, source_id: str) -> Person | None:
        from .config import settings

        return s.scalars(
            select(Person)
            .where(Person.owner == settings.owner)
            .where(Person.source == source)
            .where(Person.source_id == source_id)
        ).first()

    def _write_handles(self, s: Session, person_id: int,
                       handles: dict[tuple[str, str], bool]) -> None:
        from .config import settings

        s.execute(delete(PersonHandle).where(PersonHandle.person_id == person_id))
        for (kind, value), possible in handles.items():
            s.add(PersonHandle(owner=settings.owner, person_id=person_id,
                               kind=kind, value=(value or "")[:320], possible=bool(possible)))

    def _apply_person(self, s: Session, person: NormalizedPerson,
                      region: str) -> tuple[Person, bool]:
        """Get-or-create by (owner, source, source_id); write ONLY the sync-owned
        identity fields + phones/emails/meta and rebuild the handle index. Clears
        removed_from_source_at so a returning contact resurrects. CRM-native fields
        are never touched here. Returns (row, created)."""
        from .config import settings

        row = self._person_row(s, person.source, person.source_id)
        created = row is None
        if created:
            row = Person(owner=settings.owner, source=person.source,
                         source_id=person.source_id)
            s.add(row)
        row.display_name = _clean_name(person.display_name)
        row.first_name = _clean_name(person.first_name)
        row.last_name = _clean_name(person.last_name)
        row.nickname = _clean_name(person.nickname)
        row.organization = _clean_name(person.organization)
        row.job_title = _clean_name(person.job_title)
        # Photos: the reader hands us a TRANSIENT absolute path; persist only the
        # opaque, RELATIVE photo_key (contract: Photo storage). When a person's
        # photo changes, unlink the superseded file. Imports are function-local so
        # Task 3 stays self-contained (contact_photos lands in Task 5) and a
        # photoless person (photo_path is None) never touches the photos module.
        old_key = row.photo_key
        new_key = None
        if person.photo_path:
            from .providers import contact_photos
            new_key = contact_photos.key_for_path(person.photo_path)
        row.photo_key = new_key
        row.has_photo = bool(person.has_photo)
        if old_key and old_key != new_key:
            from .providers import contact_photos
            contact_photos.delete_photo(old_key, settings.contacts_photos_root())
        norm_phones, norm_emails, handles = _canon_entries(person.phones, person.emails, region)
        row.phones = norm_phones            # fresh list of fresh dicts -> change detected
        row.emails = norm_emails
        row.meta = {**(row.meta or {}), **(person.meta or {})}
        row.removed_from_source_at = None
        s.flush()
        self._write_handles(s, row.id, handles)
        return row, created

    def _reconcile_people(self, s: Session, source: str,
                          seen_source_ids: list[str], now: datetime) -> int:
        """Soft-delete synced people no longer present in the snapshot (never a
        hard delete; handle rows survive so history still resolves). Caller runs
        this ONLY for a clean COMPLETE_* read."""
        from .config import settings

        seen = set(seen_source_ids)
        flipped = 0
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

    @_retry_integrity
    def apply_contacts_snapshot(self, snapshot: ContactsSnapshot,
                                now: datetime) -> SyncResult:
        """The one transactional entry the sync engine (Task 5) calls. In a single
        locked transaction: on a COMPLETE_* read upsert every person + rebuild
        handles, then reconcile soft-deletions IFF no per-record error occurred
        (else commit the good upserts and record status='partial', skipping
        reconcile). A non-COMPLETE read writes NO rows — it only records state;
        ACCESS_DENIED with existing rows marks the state 'stale' (never
        soft-deletes)."""
        from .config import settings

        now = _to_utc(now)
        complete = snapshot.status in (SnapshotStatus.COMPLETE_NONEMPTY,
                                       SnapshotStatus.COMPLETE_EMPTY)
        with self._locked_write() as s:
            state = self._state_row(s)
            region = state.normalization_region or settings.contacts_default_region

            if not complete:
                if snapshot.status == SnapshotStatus.ACCESS_DENIED:
                    active = s.scalar(
                        select(func.count()).select_from(Person)
                        .where(Person.owner == settings.owner)
                        .where(Person.source == "macos_contacts")
                        .where(Person.removed_from_source_at.is_(None))
                    ) or 0
                    result_status = "access_denied"
                    state_status = "stale" if active else "access_denied"
                    access = "denied"
                else:
                    result_status, state_status, access = _FAILED_MAP[snapshot.status]
                state.status = state_status
                state.access = access
                state.last_error = snapshot.error
                return SyncResult(status=result_status, access=access,
                                  last_sync_at=aware_utc(state.last_sync_at),
                                  last_error=snapshot.error)

            imported = updated = 0
            per_record_error = False
            seen: list[str] = []
            for person in snapshot.people:
                try:
                    with s.begin_nested():          # savepoint: a bad record can't poison the batch
                        _row, created = self._apply_person(s, person, region)
                    seen.append(person.source_id)
                    imported += int(created)
                    updated += int(not created)
                except (ValueError, TypeError):
                    # DATA-TRANSFORM error only (bad record shape / handle): drop
                    # this record, commit the rest, and degrade to 'partial' with
                    # reconcile skipped. Infrastructure/DB errors (SQLAlchemyError /
                    # OperationalError) are deliberately NOT caught here -> they
                    # propagate and the whole transaction rolls back atomically.
                    per_record_error = True
                    logger.exception("apply_contacts_snapshot: record failed (%s)",
                                     getattr(person, "source_id", "?"))

            removed = 0
            if not per_record_error:
                removed = self._reconcile_people(s, "macos_contacts", seen, now)
                state.status = "ready"
                state.last_error = None
                result_status = ("empty" if snapshot.status == SnapshotStatus.COMPLETE_EMPTY
                                 else "ok")
            else:
                state.status = "error"
                state.last_error = "partial apply: one or more contacts failed to import"
                result_status = "partial"

            if state.normalization_region is None:
                state.normalization_region = region
            state.access = "granted"
            state.last_sync_at = now
            result = SyncResult(status=result_status, access="granted",
                                imported=imported, updated=updated, removed=removed,
                                last_sync_at=now, last_error=state.last_error)
            # Surviving photo keys, for the post-commit orphan sweep below.
            keep_photo_keys = set(s.scalars(
                select(Person.photo_key)
                .where(Person.owner == settings.owner)
                .where(Person.photo_key.is_not(None))
            ).all())

        # After the transaction COMMITS: sweep superseded / rolled-back / orphaned
        # photo files that no surviving row references (contract: Photo storage —
        # cleanup on re-sync). Skipped when no photos exist, which keeps Task 3
        # self-contained (contact_photos lands in Task 5).
        if keep_photo_keys:
            from .providers import contact_photos
            contact_photos.cleanup_orphans(keep_photo_keys, settings.contacts_photos_root())
        return result

    @_retry_integrity
    def upsert_person(self, person: NormalizedPerson) -> dict:
        """Single-person get-or-create + reindex (its own locked transaction).
        Convenience for granular callers/tests; the batch sync path uses
        apply_contacts_snapshot."""
        from .config import settings

        with self._locked_write() as s:
            region = self._state_row(s).normalization_region or settings.contacts_default_region
            row, _created = self._apply_person(s, person, region)
            return _person_dict(row)

    def list_people(self, *, include_removed: bool = False, q: str | None = None,
                    limit: int = 50, cursor: str | None = None) -> dict:
        """Deterministic (display_name, id) keyset page. Bounded search `q`
        (case-insensitive substring over name/nickname/organization/job title).
        Returns {"items": [...], "next_cursor": str | None}."""
        from .config import settings

        limit = max(1, min(int(limit or 50), 200))
        stmt = select(Person).where(Person.owner == settings.owner)
        if not include_removed:
            stmt = stmt.where(Person.removed_from_source_at.is_(None))
        ql = (q or "").strip()[:100]
        if ql:
            like = f"%{ql.lower()}%"
            stmt = stmt.where(or_(
                func.lower(Person.display_name).like(like),
                func.lower(Person.nickname).like(like),
                func.lower(Person.organization).like(like),
                func.lower(Person.job_title).like(like),
            ))
        if cursor:
            cname, cid = _decode_cursor(cursor)
            if cname is not None:
                stmt = stmt.where(or_(
                    Person.display_name > cname,
                    and_(Person.display_name == cname, Person.id > cid),
                ))
        stmt = stmt.order_by(Person.display_name.asc(), Person.id.asc()).limit(limit + 1)
        with self._session() as s:
            rows = s.scalars(stmt).all()
        next_cursor = None
        if len(rows) > limit:
            edge = rows[limit - 1]
            next_cursor = _encode_cursor(edge.display_name, edge.id)
            rows = rows[:limit]
        return {"items": [_person_dict(r) for r in rows], "next_cursor": next_cursor}

    def get_person(self, person_id: int) -> dict | None:
        """Fetch by id (owner-scoped). Returns soft-deleted rows too — callers
        decide; list_people hides them."""
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            return _person_dict(row) if row is not None else None

    def _apply_patch(self, s: Session, row: Person, patch: dict, region: str,
                     *, manual: bool) -> None:
        """Source-aware CRUD field application.
        - Imported rows: sync-owned identity fields are silently dropped (read-only).
        - Non-nullable fields: an explicit None is ignored (PATCH never 500s);
          nullable CRM-native fields: an explicit None clears them.
        Rebuilds handles by reassigning fresh normalized lists when phones/emails
        change (never post-flush nested mutation)."""
        new_phones = new_emails = None
        for key, value in (patch or {}).items():
            if key in _PERSON_IMMUTABLE:
                continue
            if not manual and key in _PERSON_SYNC_FIELDS:     # imported identity read-only
                continue
            if key == "phones":
                if value is not None:
                    new_phones = value
            elif key == "emails":
                if value is not None:
                    new_emails = value
            elif key in _PERSON_NAME_FIELDS:
                if value is not None:                          # non-nullable -> ignore None
                    setattr(row, key, _clean_name(value))
            elif key == "relationship":
                row.relationship = None if value is None else _clean_label(value, 32)
            elif key == "relationship_strength":
                row.relationship_strength = None if value is None else _clean_strength(value)
            elif key == "notes":
                row.notes = None if value is None else str(value)
            elif key == "pinned":
                if value is not None:
                    row.pinned = bool(value)
            elif key == "last_contacted_at":
                row.last_contacted_at = None if value is None else _to_utc(value)
            # unknown keys (and has_photo/photo_key/source) ignored -> PATCH cannot 500
        if new_phones is not None or new_emails is not None:
            phones_src = new_phones if new_phones is not None else (row.phones or [])
            emails_src = new_emails if new_emails is not None else (row.emails or [])
            s.flush()
            norm_phones, norm_emails, handles = _canon_entries(phones_src, emails_src, region)
            row.phones = norm_phones
            row.emails = norm_emails
            s.flush()
            self._write_handles(s, row.id, handles)

    @_retry_integrity
    def create_person(self, data: dict) -> dict:
        """Manual (source='manual') create; server-generates source_id. Rejects a
        whitespace-only display_name."""
        import uuid

        from .config import settings

        display = _clean_name((data or {}).get("display_name", ""))
        if not display:
            raise ValueError("display_name must not be blank")
        with self._locked_write() as s:
            region = self._state_row(s).normalization_region or settings.contacts_default_region
            row = Person(owner=settings.owner, source="manual",
                         source_id=uuid.uuid4().hex, display_name=display)
            s.add(row)
            s.flush()
            rest = {k: v for k, v in (data or {}).items() if k != "display_name"}
            self._apply_patch(s, row, rest, region, manual=True)
            return _person_dict(row)

    @_retry_integrity
    def update_person(self, person_id: int, patch: dict) -> dict | None:
        from .config import settings

        with self._locked_write() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            if row is None:
                return None
            region = self._state_row(s).normalization_region or settings.contacts_default_region
            clean = dict(patch or {})
            # Never blank an existing name with a whitespace-only value.
            if clean.get("display_name") is not None and not _clean_name(clean["display_name"]):
                clean.pop("display_name")
            self._apply_patch(s, row, clean, region, manual=(row.source == "manual"))
            return _person_dict(row)

    @_retry_integrity
    def delete_person(self, person_id: int) -> bool:
        """Hard-delete a manual row (its person_handle rows cascade). An imported
        row is never hard-deleted here — it is tombstoned (soft-deleted) so history
        still resolves; a later authoritative sync resurrects it if the source
        contact still exists. Permanent removal of imported data is the
        Disconnect/Forget lifecycle."""
        from .config import settings

        with self._locked_write() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            if row is None:
                return False
            if row.source == "manual":
                s.delete(row)
            else:
                row.removed_from_source_at = utcnow()
            return True

    def resolve_handle(self, handle: str) -> list[dict]:
        """Every person carrying this handle (shared handles -> multiple), most
        recently contacted first, INCLUDING soft-deleted people so historical
        messages still resolve. Canonicalizes with the PERSISTED
        normalization_region (falls back to settings), never the live locale."""
        from .config import settings
        from .identity import canon_handle

        with self._session() as s:
            state = s.scalars(
                select(ContactsSyncState).where(ContactsSyncState.owner == settings.owner)
            ).first()
            region = (state.normalization_region if state else None) \
                or settings.contacts_default_region
            canon = canon_handle(handle, region)
            if canon is None:
                return []
            rows = s.scalars(
                select(Person)
                .join(PersonHandle, PersonHandle.person_id == Person.id)
                .where(Person.owner == settings.owner)
                .where(PersonHandle.value == canon["normalized"])
                .order_by(case((Person.last_contacted_at.is_(None), 1), else_=0),
                          Person.last_contacted_at.desc(),
                          Person.updated_at.desc(),
                          Person.id.desc())
            ).all()
            return [_person_dict(r) for r in rows]

    @_retry_integrity
    def get_contacts_state(self) -> dict:
        """Get-or-create the single contacts_sync_state row for the owner."""
        with self._session() as s, s.begin():
            return _state_dict(self._state_row(s))

    @_retry_integrity
    def set_contacts_state(self, patch: dict) -> dict:
        """Patch consent/lifecycle fields (enable/disconnect/status/region/errors).
        Datetimes are stored aware-UTC. The router (Task 6) drives enable/disconnect;
        the sync apply writes status/access/last_sync_at itself."""
        with self._locked_write() as s:
            st = self._state_row(s)
            for key in ("enabled", "status", "access", "normalization_region", "last_error"):
                if key in patch:
                    setattr(st, key, patch[key])
            for key in ("last_sync_at", "enabled_at"):
                if key in patch:
                    setattr(st, key, _to_utc(patch[key]) if patch[key] is not None else None)
            return _state_dict(st)

    def set_contacts_enabled(self, enabled: bool, *, region: str | None = None,
                             now: datetime | None = None) -> dict:
        """Thin consent toggle over set_contacts_state (used by the Task 10 tests
        and any caller that just flips the flag). Enabling stamps enabled_at +
        status 'ready' and, when given, persists normalization_region; disabling
        sets status 'disabled'. Delegates locking/serialization to
        set_contacts_state."""
        patch: dict = {"enabled": bool(enabled)}
        if enabled:
            patch["status"] = "ready"
            patch["enabled_at"] = now or utcnow()
            if region:
                patch["normalization_region"] = region
        else:
            patch["status"] = "disabled"
        return self.set_contacts_state(patch)
```

- [ ] **Step 6: Run the store tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_people_store.py -q`
Expected: PASS (22 — 19 test functions, the non-complete parametrize contributes 4 cases).

- [ ] **Step 7: Full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` (report the count — this task adds 22 test cases to the growing M10 suite)
```bash
git add backend/app/providers/base.py backend/app/providers/macos_contacts.py \
        backend/app/config.py backend/app/store.py backend/tests/test_people_store.py
git commit -m "feat(people): store — transactional apply_contacts_snapshot + handle index + source-aware CRUD + locking + consent state (M10 s1)"
```

---

---

## Task 4: macOS Contacts reader → `ContactsSnapshot` (hardened)

The novel, macOS-specific code, and the single most safety-critical module in the slice: everything downstream keys off the *status* this reader assigns. A snapshot that misclassifies a permission blip or a corrupt store as "empty" would soft-delete every contact on the next reconcile. So `read_snapshot()` **never raises for control flow** — it classifies into the contract's `SnapshotStatus` and lets the transactional apply decide what is safe. Pure + injectable path; a fixture `.abcddb` drives the tests so no real Mac files are ever touched.

**Files:**
- Create: `backend/app/providers/macos_contacts.py`
- Create: `backend/tests/test_macos_contacts_reader.py`

**Interfaces:**
- Consumes: `NormalizedPerson` (Task 3 `providers/base.py`); the contract's *Source ID namespacing* scheme; the persisted normalization `region` (Task 3 passes `contacts_sync_state.normalization_region`).
- Produces (exact contract names/signatures):
  - `class SnapshotStatus(str, Enum)` — `COMPLETE_NONEMPTY | COMPLETE_EMPTY | ACCESS_DENIED | UNSUPPORTED_SCHEMA | MISSING_STORE | PARTIAL_READ | IO_ERROR`.
  - `@dataclass ContactsSnapshot` — `status, people, stores_total=0, stores_read=0, store_ids=[], error=None`.
  - `read_snapshot(root=DEFAULT_ROOT, *, region: str, photos_dir: str | None, enabled: bool = True) -> ContactsSnapshot` — the ONLY public read entry; never raises for control flow.
  - `probe_access(root=DEFAULT_ROOT) -> str` → `"granted" | "denied" | "unknown"` (permission probe only; never raises).
  - `is_supported() -> bool` — the platform seam: `_PLATFORM_OVERRIDE == "darwin"` when a platform is injected, else `sys.platform == "darwin"`. The connector card (Task 8) derives `configured` from this, never from raw `sys.platform`, so `configure(platform=…)` makes the card host-independent.
  - `configure(*, fake_snapshot: ContactsSnapshot | None = None, platform: str | None = None) -> None` — the test seam. A configured `fake_snapshot` makes `read_snapshot` return it verbatim and `probe_access` derive access from its status (`COMPLETE_*` → `"granted"`, `ACCESS_DENIED` → `"denied"`, else `"unknown"`); a configured non-darwin `platform` makes `probe_access` return `"denied"`. `configure()` with no args resets to real detection. (Task 10's autouse fixture calls `configure(platform="linux")`; individual tests call `configure(fake_snapshot=…)`.)
  - `DEFAULT_ROOT = "~/Library/Application Support/AddressBook"`.
- Consumed by: `store.apply_contacts_snapshot(snapshot, now)` (Task 3) — which acts on `snapshot.status`; only `COMPLETE_*` may drive reconciliation.

> **Photos in Task 4 are a no-op.** This task reads people, phones, emails, org/title, company/NULL flags, and namespaced source ids; every person comes back with `photo_path=None, has_photo=False`. The photo pass (extraction + atomic storage) is wired in **Task 5**, which edits `_extract_people` in place. Keeping the two apart lets Task 4's tests assert classification without the photo module existing yet.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_macos_contacts_reader.py`

```python
import errno
import hashlib
import os
import sqlite3

import pytest

from app.providers import macos_contacts
from app.providers.macos_contacts import (
    ContactsSnapshot, SnapshotStatus, probe_access, read_snapshot,
)

# The ABCDContact entity number is DISCOVERED at runtime via Z_PRIMARYKEY. We
# deliberately pick 19 (never 1) so a hardcoded entity number would fail loudly.
_ENT_CONTACT = 19
_ENT_GROUP = 20

_SCHEMA = """
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


def _new_store(path, *, contact_entity_name="ABCDContact", schema=_SCHEMA):
    con = sqlite3.connect(path)
    con.executescript(schema)
    if contact_entity_name is not None:
        con.execute("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, ?)",
                    (_ENT_CONTACT, contact_entity_name))
    con.execute("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, 'ABCDGroup')",
                (_ENT_GROUP,))
    return con


def _seed_local(con):
    # a normal person, with a wrapped-label phone + email
    con.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZDISPLAYFLAGS)"
        " VALUES (1, ?, 'UID-1:ABPerson', 'Jane', 'Doe', 0)", (_ENT_CONTACT,))
    con.execute("INSERT INTO ZABCDPHONENUMBER (Z_PK, ZOWNER, ZFULLNUMBER, ZLABEL, ZORDERINGINDEX)"
                " VALUES (1, 1, '(555) 123-4567', '_$!<Mobile>!$_', 0)")
    con.execute("INSERT INTO ZABCDEMAILADDRESS (Z_PK, ZOWNER, ZADDRESS, ZLABEL, ZORDERINGINDEX)"
                " VALUES (1, 1, 'Jane@iCloud.com', '_$!<Home>!$_', 0)")
    # a company row (ZDISPLAYFLAGS bit0 set)
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZORGANIZATION, ZDISPLAYFLAGS)"
                " VALUES (2, ?, 'UID-2:ABPerson', 'Acme Inc', 1)", (_ENT_CONTACT,))
    # a NULL-displayflags row (must read as not-company, never crash)
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS)"
                " VALUES (3, ?, 'UID-3:ABPerson', 'Solo', NULL)", (_ENT_CONTACT,))
    # a GROUP row (different Z_ENT) that MUST be excluded
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZNICKNAME)"
                " VALUES (4, ?, 'UID-G:ABGroup', 'My Group')", (_ENT_GROUP,))


@pytest.fixture
def ab_root(tmp_path):
    """A top-level 'local' store plus a SECOND store under Sources/<UUID> that
    holds a UNIQUE contact — proving multi-store union and per-store namespacing."""
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = _new_store(str(root / "AddressBook-v22.abcddb"))
    _seed_local(con)
    con.commit()
    con.close()

    src = root / "Sources" / "ABCDEF-1234"
    src.mkdir(parents=True)
    con2 = _new_store(str(src / "AddressBook-v22.abcddb"))
    con2.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZDISPLAYFLAGS)"
        " VALUES (7, ?, 'UID-Z:ABPerson', 'Zed', 'Unique', 0)", (_ENT_CONTACT,))
    con2.commit()
    con2.close()
    return str(root)


def test_complete_nonempty_unions_both_stores(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert isinstance(snap, ContactsSnapshot)
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.stores_total == 2 and snap.stores_read == 2
    assert set(snap.store_ids) == {"local", "ABCDEF-1234"}
    names = {p.display_name for p in snap.people}
    assert "Jane Doe" in names
    assert "Zed Unique" in names          # the UNIQUE contact from the 2nd store was imported


def test_second_store_contact_is_namespaced_to_its_store(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    zed = next(p for p in snap.people if p.display_name == "Zed Unique")
    assert zed.meta["store_id"] == "ABCDEF-1234"
    assert zed.meta["zuniqueid"] == "UID-Z:ABPerson"
    assert zed.meta["z_pk"] == 7


def test_source_id_is_hashed_namespaced_never_raw(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    jane = next(p for p in snap.people if p.display_name == "Jane Doe")
    # sha1 hex, 40 chars, fits String(128); NEVER an unqualified 'zpk:1'
    assert len(jane.source_id) == 40
    assert all(c in "0123456789abcdef" for c in jane.source_id)
    assert "zpk:" not in jane.source_id
    assert jane.source_id == hashlib.sha1(b"local:UID-1:ABPerson").hexdigest()
    # raw ids are preserved in meta for debugging
    assert jane.meta["zuniqueid"] == "UID-1:ABPerson"
    assert jane.meta["store_id"] == "local"


def test_labels_unwrapped(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    jane = next(p for p in snap.people if p.display_name == "Jane Doe")
    assert jane.phones[0]["value"] == "(555) 123-4567"     # reader keeps the RAW value
    assert jane.phones[0]["label"] == "Mobile"             # _$!<Mobile>!$_ unwrapped
    assert jane.emails[0]["label"] == "Home"


def test_groups_excluded(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert all("ABGroup" not in (p.meta.get("zuniqueid") or "") for p in snap.people)
    assert all(p.display_name != "My Group" for p in snap.people)


def test_company_and_null_displayflags(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    acme = next(p for p in snap.people if p.organization == "Acme Inc")
    assert acme.meta["is_company"] is True
    assert acme.display_name == "Acme Inc"
    solo = next(p for p in snap.people if p.first_name == "Solo")
    assert solo.meta["is_company"] is False


def test_complete_empty_when_store_present_but_no_contacts(tmp_path):
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = _new_store(str(root / "AddressBook-v22.abcddb"))   # entity present, zero contact rows
    con.commit()
    con.close()
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.COMPLETE_EMPTY
    assert snap.people == []                                 # [] people is ONLY ever COMPLETE_EMPTY


def test_missing_store(tmp_path):
    snap = read_snapshot(str(tmp_path / "nope"), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.MISSING_STORE
    assert snap.people == []


def test_unsupported_when_abcdcontact_entity_absent(tmp_path):
    # tables all present, but Z_PRIMARYKEY has no ABCDContact row -> UNSUPPORTED, not EMPTY
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = _new_store(str(root / "AddressBook-v22.abcddb"), contact_entity_name=None)
    con.execute("INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS)"
                " VALUES (1, 19, 'UID-1:ABPerson', 'Jane', 0)")
    con.commit()
    con.close()
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.UNSUPPORTED_SCHEMA
    assert snap.people == []


def test_unsupported_when_required_table_missing(tmp_path):
    root = tmp_path / "AddressBook"
    root.mkdir()
    con = sqlite3.connect(str(root / "AddressBook-v22.abcddb"))
    con.executescript("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);")  # no ZABCDRECORD
    con.execute("INSERT INTO Z_PRIMARYKEY VALUES (19, 'ABCDContact')")
    con.commit()
    con.close()
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.UNSUPPORTED_SCHEMA


def test_io_error_on_corrupt_store(tmp_path):
    root = tmp_path / "AddressBook"
    root.mkdir()
    (root / "AddressBook-v22.abcddb").write_bytes(b"this is definitely not a sqlite database")
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.IO_ERROR
    assert snap.people == []


def test_partial_read_when_one_store_fails(ab_root):
    # corrupt the SECOND store; the first still reads fine -> PARTIAL_READ (reconcile unsafe)
    bad = os.path.join(ab_root, "Sources", "ABCDEF-1234", "AddressBook-v22.abcddb")
    with open(bad, "wb") as fh:
        fh.write(b"corrupted")
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.PARTIAL_READ
    assert snap.stores_total == 2 and snap.stores_read == 1
    assert snap.store_ids == ["local"]
    assert any(p.display_name == "Jane Doe" for p in snap.people)   # good store still imported


def test_access_denied_via_eperm(ab_root, monkeypatch):
    # simulate Full Disk Access denied: the private-snapshot copy hits EPERM
    def _eperm(_path):
        raise PermissionError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(macos_contacts, "_private_snapshot", _eperm)
    snap = read_snapshot(ab_root, region="US", photos_dir=None)
    assert snap.status is SnapshotStatus.ACCESS_DENIED
    assert snap.people == []                        # a denied read NEVER yields rows


def test_disabled_reads_nothing(ab_root):
    snap = read_snapshot(ab_root, region="US", photos_dir=None, enabled=False)
    assert snap.people == []
    assert snap.status is not SnapshotStatus.COMPLETE_NONEMPTY   # no writes/reconcile possible


def test_error_string_is_redacted(tmp_path):
    snap = read_snapshot(str(tmp_path / "SecretUser" / "nope"), region="US", photos_dir=None)
    assert snap.error and "SecretUser" not in snap.error         # no home path / username leak


def test_probe_access_granted_on_readable_fixture(ab_root, monkeypatch):
    macos_contacts.configure()   # clear the autouse platform seam; drive via _is_darwin
    monkeypatch.setattr(macos_contacts, "_is_darwin", lambda: True)
    assert probe_access(ab_root) == "granted"


def test_probe_access_denied_on_missing(tmp_path, monkeypatch):
    macos_contacts.configure()
    monkeypatch.setattr(macos_contacts, "_is_darwin", lambda: True)
    assert probe_access(str(tmp_path / "none")) == "denied"


def test_probe_access_unknown_off_darwin(ab_root, monkeypatch):
    macos_contacts.configure()
    monkeypatch.setattr(macos_contacts, "_is_darwin", lambda: False)
    assert probe_access(ab_root) == "unknown"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_macos_contacts_reader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers.macos_contacts'`.

- [ ] **Step 3: Write the reader** — `backend/app/providers/macos_contacts.py`

```python
"""Read the local macOS Contacts (AddressBook) store, one-way and read-only.

There is no supported API; we open the Core Data SQLite stores directly. The
schema is stable at AddressBook-v22 (macOS 13–26), but we treat it DEFENSIVELY:
the ABCDContact entity number is discovered at runtime via Z_PRIMARYKEY (never
hardcoded), required tables/columns are probed via sqlite_master/PRAGMA, and any
single-store failure is isolated and classified rather than raised.

`read_snapshot()` NEVER raises for control flow. It returns a typed
`ContactsSnapshot` whose `status` tells the caller exactly what happened:

  COMPLETE_NONEMPTY / COMPLETE_EMPTY  every discovered store read OK (>=1 / 0 rows)
  ACCESS_DENIED                       Full Disk Access missing -> EPERM on open
  UNSUPPORTED_SCHEMA                  missing ABCDContact entity or a required table
  MISSING_STORE                       no AddressBook store files present
  PARTIAL_READ                        >=1 store read but >=1 failed -> reconcile UNSAFE
  IO_ERROR                            sqlite corruption / generic I/O failure

Only COMPLETE_* may drive soft-delete reconciliation downstream; every other
status is a no-op for row removal. That is the whole point: a permission blip, a
corrupt file, or a half-read multi-store set can never look like "every contact
was deleted". A `[]` people list is ONLY ever COMPLETE_EMPTY — a missing entity
or table is UNSUPPORTED_SCHEMA, not empty.

Live-read safety (why NOT immutable=1): the AddressBook store is a WAL-mode
SQLite database that Contacts.app / cloudd write to concurrently. Opening it with
`immutable=1` avoids locks but tells SQLite the file never changes, so it IGNORES
the -wal frames — yielding a stale/inconsistent view and masking real corruption.
Instead we take a private point-in-time SNAPSHOT: copy the store plus its
-wal/-shm sidecars into a per-read temp dir and read the COPY with mode=ro +
PRAGMA query_only=ON + a bounded busy_timeout inside a single read transaction.
Nothing writes the copy, so the read is consistent, never blocks or corrupts the
live store, and still applies committed -wal frames (because we did NOT set
immutable). The temp dir is removed after each store is read.
"""
from __future__ import annotations

import errno
import glob
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .base import NormalizedPerson

logger = logging.getLogger("scuffed_os.macos_contacts")

DEFAULT_ROOT = "~/Library/Application Support/AddressBook"

_STORE_FILENAME = "AddressBook-v22.abcddb"
_REQUIRED_TABLES = ("Z_PRIMARYKEY", "ZABCDRECORD")
# Optional record columns probed per store; absent ones default to None so an
# older/newer schema variant degrades instead of raising.
_RECORD_OPTIONAL = (
    "ZUNIQUEID", "ZFIRSTNAME", "ZLASTNAME", "ZNICKNAME",
    "ZORGANIZATION", "ZJOBTITLE", "ZDISPLAYFLAGS",
)


class SnapshotStatus(str, Enum):
    COMPLETE_NONEMPTY = "complete_nonempty"
    COMPLETE_EMPTY = "complete_empty"
    ACCESS_DENIED = "access_denied"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    MISSING_STORE = "missing_store"
    PARTIAL_READ = "partial_read"
    IO_ERROR = "io_error"


@dataclass
class ContactsSnapshot:
    status: SnapshotStatus
    people: list                                    # list[NormalizedPerson]; only for COMPLETE_*
    stores_total: int = 0
    stores_read: int = 0
    store_ids: list = field(default_factory=list)   # stable ids of stores read OK
    error: str | None = None                        # redacted; never a path/username/DSN


# ---- per-store failure taxonomy (classified, never surfaced raw) -------------
class _StoreFailure(Exception):
    pass


class _AccessDenied(_StoreFailure):
    pass


class _UnsupportedSchema(_StoreFailure):
    pass


class _IOFailure(_StoreFailure):
    pass


# ---- test seam (contract: Testing/CI seam) ----------------------------------
# configure(fake_snapshot=..., platform=...) injects a canned snapshot and/or a
# platform so tests never touch the real AddressBook. The autouse suite fixture
# (Task 10) installs a non-darwin platform; individual tests install a fake
# snapshot (which read_snapshot returns verbatim and probe_access derives access
# from). configure() with no args resets to real detection.
_FAKE_SNAPSHOT: "ContactsSnapshot | None" = None
_PLATFORM_OVERRIDE: str | None = None


def configure(*, fake_snapshot: "ContactsSnapshot | None" = None,
              platform: str | None = None) -> None:
    """Install (or clear) the read/probe test seam."""
    global _FAKE_SNAPSHOT, _PLATFORM_OVERRIDE
    _FAKE_SNAPSHOT = fake_snapshot
    _PLATFORM_OVERRIDE = platform


def _is_darwin() -> bool:
    if _PLATFORM_OVERRIDE is not None:
        return _PLATFORM_OVERRIDE == "darwin"
    return sys.platform == "darwin"


def is_supported() -> bool:
    """Public platform seam (contract: Testing/CI seam): True on a macOS host with
    the AddressBook API. Returns ``_PLATFORM_OVERRIDE == "darwin"`` when a platform
    is injected, else ``sys.platform == "darwin"`` (this is exactly ``_is_darwin``).
    Connector/UI code MUST call this instead of reading raw ``sys.platform`` so
    ``configure(platform=…)`` drives platform detection deterministically on macOS
    dev + CI alike. Permission (FDA) is a SEPARATE concern — see ``probe_access``."""
    return _is_darwin()


def _redact(path: str) -> str:
    """Errors must never leak a home path / username -> basename only."""
    return os.path.basename(os.path.normpath(path)) or path


def _store_paths(root: str) -> list[str]:
    """The top-level store plus every Sources/<UUID> store, in a stable order."""
    base = Path(os.path.expanduser(root))
    paths: list[str] = []
    top = base / _STORE_FILENAME
    if top.exists():
        paths.append(str(top))
    paths.extend(sorted(glob.glob(str(base / "Sources" / "*" / _STORE_FILENAME))))
    return paths


def _store_id(root: str, db_path: str) -> str:
    """Stable per-store id: the Sources/<UUID> folder name, 'local' for the
    top-level store, else sha1(abspath). Namespaces source_id so the SAME
    ZUNIQUEID in two stores can never collide."""
    p = Path(db_path).resolve()
    parent = p.parent
    if parent.parent.name == "Sources" and parent.name:
        return parent.name
    base = Path(os.path.expanduser(root)).resolve()
    if parent == base:
        return "local"
    return hashlib.sha1(str(p).encode()).hexdigest()


def _source_id(store_id: str, zuniqueid: str | None, z_pk: int) -> str:
    """Contract: sha1(f"{store_id}:{zuniqueid or ('zpk:'+str(z_pk))}") -> hex(40),
    fits String(128), never an unqualified 'zpk:1'."""
    raw = zuniqueid or f"zpk:{z_pk}"
    return hashlib.sha1(f"{store_id}:{raw}".encode()).hexdigest()


def _private_snapshot(db_path: str) -> tuple[str, str]:
    """Copy the store + its -wal/-shm sidecars into a private temp dir so we read
    a consistent point-in-time image without touching the live store. Returns
    (copied_store_path, tmpdir). Raises PermissionError (EPERM) if FDA is denied —
    shutil.copy2 opens the source, which is where TCC surfaces the denial."""
    tmpdir = tempfile.mkdtemp(prefix="scuffedos_ab_")
    dst = os.path.join(tmpdir, os.path.basename(db_path))
    shutil.copy2(db_path, dst)                       # EPERM / ENOENT surface here
    for suffix in ("-wal", "-shm"):
        side = db_path + suffix
        if os.path.exists(side):
            try:
                shutil.copy2(side, dst + suffix)     # sidecars are best-effort
            except OSError:
                pass
    return dst, tmpdir


def _connect_ro(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    con.isolation_level = None                       # we drive the read txn explicitly
    con.execute("PRAGMA query_only=ON")              # belt-and-suspenders: no writes
    con.execute("PRAGMA busy_timeout=5000")          # bounded wait, never hang
    return con


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _unwrap_label(raw: str | None) -> str:
    """'_$!<Mobile>!$_' -> 'Mobile'; custom labels pass through unchanged."""
    if not raw:
        return ""
    if raw.startswith("_$!<") and raw.endswith(">!$_"):
        return raw[4:-4]
    return raw


def _contact_entity(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'ABCDContact'"
    ).fetchone()
    if row is None or row[0] is None:
        raise _UnsupportedSchema("no ABCDContact entity in Z_PRIMARYKEY")
    return int(row[0])


def _require_schema(con: sqlite3.Connection) -> None:
    """Probe the schema for real (this also forces the first read of the file, so
    a corrupt/non-sqlite store raises sqlite3.DatabaseError here -> IO_ERROR)."""
    present = _tables(con)
    missing = [t for t in _REQUIRED_TABLES if t not in present]
    if missing:
        raise _UnsupportedSchema(f"missing required table(s): {', '.join(missing)}")
    rec_cols = _columns(con, "ZABCDRECORD")
    if "Z_PK" not in rec_cols or "Z_ENT" not in rec_cols:
        raise _UnsupportedSchema("ZABCDRECORD lacks Z_PK/Z_ENT")


def _extract_people(con: sqlite3.Connection, db_path: str, store_id: str,
                    region: str, photos_dir: str | None) -> list[NormalizedPerson]:
    """Build NormalizedPerson rows from one already-validated store connection.
    `region`/`db_path`/`photos_dir` are threaded for the photo pass wired in
    Task 5; identity canonicalization stays in the store (contract). Task 4 leaves
    every person photoless."""
    ent = _contact_entity(con)
    rec_cols = _columns(con, "ZABCDRECORD")
    select_cols = ["Z_PK"] + [c for c in _RECORD_OPTIONAL if c in rec_cols]
    idx = {name: i for i, name in enumerate(select_cols)}

    tables = _tables(con)
    has_phone = "ZABCDPHONENUMBER" in tables
    has_email = "ZABCDEMAILADDRESS" in tables

    rows = con.execute(
        f"SELECT {', '.join(select_cols)} FROM ZABCDRECORD WHERE Z_ENT = ?",
        (ent,),
    ).fetchall()

    people: list[NormalizedPerson] = []
    for row in rows:
        def col(name):
            return row[idx[name]] if name in idx else None

        z_pk = row[0]
        uid = col("ZUNIQUEID")
        src_id = _source_id(store_id, uid, z_pk)
        first = col("ZFIRSTNAME") or ""
        last = col("ZLASTNAME") or ""
        nick = col("ZNICKNAME") or ""
        org = col("ZORGANIZATION") or ""
        job = col("ZJOBTITLE") or ""
        is_company = bool((col("ZDISPLAYFLAGS") or 0) & 1)

        phones = []
        if has_phone:
            for (num, label) in con.execute(
                "SELECT ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER "
                "WHERE ZOWNER = ? ORDER BY ZORDERINGINDEX", (z_pk,)
            ):
                if num:
                    phones.append({"value": num, "label": _unwrap_label(label)})
        emails = []
        if has_email:
            for (addr, label) in con.execute(
                "SELECT ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS "
                "WHERE ZOWNER = ? ORDER BY ZORDERINGINDEX", (z_pk,)
            ):
                if addr:
                    emails.append({"value": addr, "label": _unwrap_label(label)})

        display = (org.strip() if is_company
                   else " ".join(x for x in (first, last) if x).strip())
        display = display or nick or org or (uid or f"zpk:{z_pk}")

        people.append(NormalizedPerson(
            source="macos_contacts",
            source_id=src_id,
            display_name=display,
            first_name=first, last_name=last, nickname=nick,
            organization=org, job_title=job,
            phones=phones, emails=emails,
            photo_path=None, has_photo=False,        # photos wired in Task 5
            meta={"is_company": is_company, "store_id": store_id,
                  "zuniqueid": uid, "z_pk": z_pk},
        ))
    return people


def _read_store(db_path: str, store_id: str, region: str,
                photos_dir: str | None) -> list[NormalizedPerson]:
    """Read ONE store from a private snapshot. Classifies its failure mode by
    raising an _AccessDenied / _UnsupportedSchema / _IOFailure; never returns raw."""
    try:
        snap_path, tmpdir = _private_snapshot(db_path)
    except PermissionError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            raise _AccessDenied(f"Full Disk Access denied for {_redact(db_path)}") from exc
        raise _IOFailure(f"cannot copy {_redact(db_path)}: {exc.strerror}") from exc
    except OSError as exc:
        raise _IOFailure(f"cannot copy {_redact(db_path)}: {exc.strerror or exc}") from exc

    try:
        try:
            con = _connect_ro(snap_path)
        except sqlite3.DatabaseError as exc:
            raise _IOFailure(f"cannot open {_redact(db_path)}: {exc}") from exc
        try:
            con.execute("BEGIN")                     # one consistent read snapshot
            _require_schema(con)
            return _extract_people(con, db_path, store_id, region, photos_dir)
        except _UnsupportedSchema:
            raise
        except sqlite3.DatabaseError as exc:         # corrupt / not-a-db / image malformed
            raise _IOFailure(f"corrupt store {_redact(db_path)}: {exc}") from exc
        finally:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def read_snapshot(root: str = DEFAULT_ROOT, *, region: str,
                  photos_dir: str | None, enabled: bool = True) -> ContactsSnapshot:
    """Classify + read every AddressBook store under `root`. NEVER raises for
    control flow. See the module docstring for the status matrix."""
    if _FAKE_SNAPSHOT is not None:      # test seam: return the injected snapshot verbatim
        return _FAKE_SNAPSHOT
    if not enabled:
        # Consent gate. The sync engine already short-circuits to a 'disabled'
        # SyncResult before ever calling us; this is defense-in-depth so a direct
        # or mistaken call with consent off does ZERO filesystem/DB work and
        # cannot mutate rows (MISSING_STORE never soft-deletes or marks stale).
        return ContactsSnapshot(status=SnapshotStatus.MISSING_STORE, people=[],
                                error="contacts import disabled")

    paths = _store_paths(root)
    if not paths:
        return ContactsSnapshot(status=SnapshotStatus.MISSING_STORE, people=[],
                                error=f"no AddressBook store under {_redact(root)}")

    people: list[NormalizedPerson] = []
    store_ids: list[str] = []
    stores_total = len(paths)
    denied = unsupported = io_error = False
    first_error: str | None = None

    for path in paths:
        sid = _store_id(root, path)
        try:
            batch = _read_store(path, sid, region, photos_dir)
        except _AccessDenied as exc:
            denied = True
            first_error = first_error or str(exc)
            continue
        except _UnsupportedSchema as exc:
            unsupported = True
            first_error = first_error or str(exc)
            continue
        except _IOFailure as exc:
            io_error = True
            first_error = first_error or str(exc)
            continue
        except Exception as exc:                     # a surprise must never propagate
            io_error = True
            first_error = first_error or f"unexpected read error: {exc}"
            logger.exception("unexpected error reading a contacts store")
            continue
        people.extend(batch)
        store_ids.append(sid)

    stores_read = len(store_ids)

    if stores_read == 0:
        # Nothing read successfully: pick the most actionable failure.
        if denied:
            status = SnapshotStatus.ACCESS_DENIED
        elif unsupported:
            status = SnapshotStatus.UNSUPPORTED_SCHEMA
        elif io_error:
            status = SnapshotStatus.IO_ERROR
        else:
            status = SnapshotStatus.MISSING_STORE
        return ContactsSnapshot(status=status, people=[], stores_total=stores_total,
                                stores_read=0, store_ids=[], error=first_error)

    if stores_read < stores_total:
        # Some stores read, some failed -> reconciliation would soft-delete the
        # contacts that live in the unread store(s). Mark PARTIAL_READ.
        return ContactsSnapshot(status=SnapshotStatus.PARTIAL_READ, people=people,
                                stores_total=stores_total, stores_read=stores_read,
                                store_ids=store_ids, error=first_error)

    status = (SnapshotStatus.COMPLETE_NONEMPTY if people
              else SnapshotStatus.COMPLETE_EMPTY)
    return ContactsSnapshot(status=status, people=people, stores_total=stores_total,
                            stores_read=stores_read, store_ids=store_ids, error=None)


def probe_access(root: str = DEFAULT_ROOT) -> str:
    """'granted' | 'denied' | 'unknown' — a permission probe only, never raises.
    Attempts a REAL open (contract: never trust os.access()): an EPERM/EACCES from
    TCC means Full Disk Access is missing. Test seam: a configured fake_snapshot
    derives access from its status; a configured non-darwin platform -> 'denied'."""
    if _FAKE_SNAPSHOT is not None:
        st = _FAKE_SNAPSHOT.status
        if st in (SnapshotStatus.COMPLETE_NONEMPTY, SnapshotStatus.COMPLETE_EMPTY):
            return "granted"                         # a COMPLETE fake read means access
        if st == SnapshotStatus.ACCESS_DENIED:
            return "denied"
        return "unknown"
    if _PLATFORM_OVERRIDE is not None and _PLATFORM_OVERRIDE != "darwin":
        return "denied"                              # injected non-darwin -> deterministic
    if not _is_darwin():
        return "unknown"                             # can't determine off macOS
    paths = _store_paths(root)
    if not paths:
        return "denied"
    try:
        with open(paths[0], "rb") as fh:
            fh.read(16)
    except PermissionError as exc:
        return "denied" if exc.errno in (errno.EPERM, errno.EACCES) else "unknown"
    except OSError:
        return "unknown"
    return "granted"
```

> **Why the private-snapshot route (and not `mode=ro` on the live file).** The contract offers two hardened options; we take the snapshot because the AddressBook store is WAL-mode and actively written by Contacts.app / cloudd. A live cross-process read risks `SQLITE_BUSY` or a torn view; `immutable=1` would dodge the locks but silently ignore the `-wal` frames, returning a stale/inconsistent snapshot AND masking genuine corruption (exactly the misclassification this module exists to prevent). Copying the store + `-wal`/`-shm` into a private temp dir and reading the copy with `mode=ro` + `query_only=ON` + a bounded `busy_timeout` inside one read transaction gives a consistent point-in-time view, never disturbs the live store, and — because we did NOT set `immutable` — still reflects committed WAL frames. The manual `BEGIN`/`ROLLBACK` keeps all of a store's SELECTs on a single snapshot even though contention on our private copy is nil.

> **How the statuses are told apart.** FDA denial surfaces as a `PermissionError(EPERM)` when we *copy* the file (we do a real filesystem read, never `os.access()`), classified `_AccessDenied` → `ACCESS_DENIED`. A missing `ABCDContact` entity or a missing required table is probed via `sqlite_master`/`PRAGMA` and raises `_UnsupportedSchema` → `UNSUPPORTED_SCHEMA` (never `COMPLETE_EMPTY`). Corruption / not-a-database / disk-image-malformed raises `sqlite3.DatabaseError` at first read → `IO_ERROR`. No store files → `MISSING_STORE`. A mixed multi-store outcome → `PARTIAL_READ`. Only "every discovered store read OK" yields `COMPLETE_NONEMPTY`/`COMPLETE_EMPTY`.

- [ ] **Step 4: Run the reader tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_macos_contacts_reader.py -q`
Expected: PASS (19).

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` (report the count; expect **+19** over Task 3)
```bash
git add backend/app/providers/macos_contacts.py backend/tests/test_macos_contacts_reader.py
git commit -m "feat(people): read-only AddressBook reader -> classified ContactsSnapshot (M10 s1)"
```

---

## Task 5: Contact photo storage (`providers/contact_photos.py`) + reader photo pass

Photos are the one piece of contact data that stays on the **backend host's App Support filesystem** (never in PostgreSQL): the database persists only an opaque, RELATIVE `photo_key`, and the bytes live on disk under that name. This task delivers the storage module — magic-byte type detection, atomic writes, containment-checked serving, and orphan cleanup — and wires the reader's photo pass into `_extract_people`. Every photo failure is swallowed so a bad thumbnail never aborts a snapshot; the person is simply imported without a photo.

**Files:**
- Create: `backend/app/providers/contact_photos.py`
- Modify: `backend/app/providers/macos_contacts.py` (add the photo pass to `_extract_people` + a `_thumbnail_bytes` helper + the `contact_photos` import + `ZTHUMBNAILIMAGEDATA` to `_RECORD_OPTIONAL`)
- Create: `backend/tests/test_contact_photos.py`
- Create: `backend/tests/test_macos_contacts_photos.py`

**Interfaces:**
- Consumes: `settings.app_support_dir` (M8) + `settings.contacts_photos_dir` (config task); the contract's *Photo storage* `photo_key` scheme.
- Produces:
  - `detect_media_type(data: bytes) -> tuple[str, str] | None` — `(ext, content_type)` from magic bytes (JPEG/PNG/HEIC/GIF), else `None`.
  - `content_type_for(key: str) -> str` — Content-Type for a stored key's extension.
  - `resolve_root(settings) -> str` — the photos root (App Support + `contacts_photos_dir`; relative resolves UNDER App Support, never `./data`).
  - `photo_key(store_id, source_id, ext) -> str` — `f"{sha256(store_id:source_id)}.{ext}"`.
  - `store_photo(data, *, store_id, source_id, photos_root) -> str | None` — atomic write; returns the opaque relative key or `None`.
  - `resolve_photo(key, photos_root) -> str | None` — containment-checked absolute path, or `None`.
  - `key_for_path(photo_path) -> str` — the opaque relative key from the reader's transient absolute path (basename; flat layout).
  - `delete_photo(key, photos_root) -> None` and `cleanup_orphans(keep_keys: set[str], photos_root) -> int`.
- Consumed by: the reader's photo pass (this task) writes files and sets `NormalizedPerson.photo_path` to the transient absolute path; `store.apply_contacts_snapshot` (Task 3) converts it to `photo_key` via `key_for_path` and calls `cleanup_orphans` after a successful re-sync; the `/photo` router (later task) serves via `resolve_photo`.

- [ ] **Step 1: Write the failing storage test** — `backend/tests/test_contact_photos.py`

```python
import hashlib
import os
from types import SimpleNamespace

from app.providers import contact_photos as cp

# minimal but real magic-byte headers
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 16
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16
_GIF = b"GIF89a" + b"\x00" * 16


def test_detect_media_types():
    assert cp.detect_media_type(_JPEG) == ("jpg", "image/jpeg")
    assert cp.detect_media_type(_PNG) == ("png", "image/png")
    assert cp.detect_media_type(_HEIC) == ("heic", "image/heic")     # NOT assumed JFIF
    assert cp.detect_media_type(_GIF) == ("gif", "image/gif")
    assert cp.detect_media_type(b"not an image at all") is None
    assert cp.detect_media_type(b"") is None


def test_store_and_resolve_roundtrip(tmp_path):
    key = cp.store_photo(_PNG, store_id="local", source_id="abc", photos_root=str(tmp_path))
    assert key == hashlib.sha256(b"local:abc").hexdigest() + ".png"   # opaque, relative
    path = cp.resolve_photo(key, str(tmp_path))
    assert path and os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read() == _PNG
    assert cp.content_type_for(key) == "image/png"
    assert cp.key_for_path(path) == key


def test_media_type_drives_extension(tmp_path):
    jpg = cp.store_photo(_JPEG, store_id="s", source_id="j", photos_root=str(tmp_path))
    heic = cp.store_photo(_HEIC, store_id="s", source_id="h", photos_root=str(tmp_path))
    assert jpg.endswith(".jpg") and cp.content_type_for(jpg) == "image/jpeg"
    assert heic.endswith(".heic") and cp.content_type_for(heic) == "image/heic"


def test_store_photo_rejects_malformed_image(tmp_path):
    assert cp.store_photo(b"garbage bytes here", store_id="s", source_id="i",
                          photos_root=str(tmp_path)) is None
    assert os.listdir(tmp_path) == []                     # nothing written


def test_resolve_missing_file_returns_none(tmp_path):
    key = hashlib.sha256(b"x:y").hexdigest() + ".jpg"
    assert cp.resolve_photo(key, str(tmp_path)) is None


def test_containment_rejects_parent_traversal(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("top secret")
    assert cp.resolve_photo("../secret.txt", str(root)) is None


def test_containment_rejects_symlink_escape(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    os.symlink(secret, root / "escape.jpg")
    assert cp.resolve_photo("escape.jpg", str(root)) is None


def test_atomic_write_leaves_no_partial_on_replace_failure(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(cp.os, "replace", _boom)
    assert cp.store_photo(_PNG, store_id="s", source_id="i",
                          photos_root=str(tmp_path)) is None
    # the temp is cleaned up; no destination file survives
    assert [f for f in os.listdir(tmp_path) if not f.startswith(".tmp_photo_")] == []


def test_store_photo_swallows_permission_error(tmp_path, monkeypatch):
    def _denied(*a, **k):
        raise PermissionError("nope")
    monkeypatch.setattr(cp.os, "makedirs", _denied)
    assert cp.store_photo(_PNG, store_id="s", source_id="i",
                          photos_root=str(tmp_path / "sub")) is None   # never raises


def test_cleanup_orphans_removes_unreferenced(tmp_path):
    k1 = cp.store_photo(_PNG, store_id="s", source_id="one", photos_root=str(tmp_path))
    k2 = cp.store_photo(_PNG, store_id="s", source_id="two", photos_root=str(tmp_path))
    removed = cp.cleanup_orphans({k1}, str(tmp_path))
    assert removed == 1
    assert cp.resolve_photo(k1, str(tmp_path)) is not None
    assert cp.resolve_photo(k2, str(tmp_path)) is None


def test_delete_photo_removes_file(tmp_path):
    key = cp.store_photo(_PNG, store_id="s", source_id="i", photos_root=str(tmp_path))
    cp.delete_photo(key, str(tmp_path))
    assert cp.resolve_photo(key, str(tmp_path)) is None
    cp.delete_photo(key, str(tmp_path))               # idempotent; no raise on a gone file


def test_resolve_root_relative_goes_under_app_support(tmp_path):
    s = SimpleNamespace(app_support_dir=str(tmp_path / "AppSupport"),
                        contacts_photos_dir="contact_photos")
    assert cp.resolve_root(s) == os.path.join(str(tmp_path / "AppSupport"), "contact_photos")


def test_resolve_root_absolute_kept(tmp_path):
    s = SimpleNamespace(app_support_dir="~/whatever",
                        contacts_photos_dir=str(tmp_path / "abs_photos"))
    assert cp.resolve_root(s) == str(tmp_path / "abs_photos")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contact_photos.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers.contact_photos'`.

- [ ] **Step 3: Write the storage module** — `backend/app/providers/contact_photos.py`

```python
"""Contact-photo storage (M10 s1).

Thumbnails extracted from the local AddressBook are written to the backend host's
App Support directory — NOT into PostgreSQL and NOT under ./data. The database
stores only an OPAQUE, RELATIVE photo key (sha256 of store_id:source_id + the
detected extension); the bytes live on disk keyed by that name in a flat layout.

Hardening:
- media type detected from MAGIC BYTES (JPEG/PNG/HEIC/GIF) -> correct extension +
  Content-Type; we never assume JFIF.
- writes are ATOMIC (temp file in the same dir + os.replace on the same fs).
- serving resolves the key against the photos root with a CONTAINMENT check
  (realpath must stay under the root), so a crafted / symlinked / '..' key cannot
  escape the directory.
- every failure (permission, disk-full, invalid filename, malformed image) is
  swallowed and returns a falsey result -> a photo problem NEVER aborts a
  contacts snapshot; the person is simply imported without a photo.
- cleanup removes superseded / orphaned files on re-sync, forget, and delete.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile

logger = logging.getLogger("scuffed_os.contact_photos")

_CONTENT_TYPE = {
    "jpg": "image/jpeg", "png": "image/png",
    "heic": "image/heic", "gif": "image/gif",
}
# ISO-BMFF 'ftyp' brands that mean HEIF/HEIC (Apple contact photos on modern macOS)
_HEIC_BRANDS = {b"heic", b"heix", b"heif", b"hevc", b"hevx", b"mif1", b"msf1"}


def detect_media_type(data: bytes) -> tuple[str, str] | None:
    """(ext, content_type) from magic bytes, or None if unrecognized."""
    if not data or len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return ("jpg", "image/jpeg")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ("png", "image/png")
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return ("heic", "image/heic")
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ("gif", "image/gif")
    return None


def content_type_for(key: str) -> str:
    ext = key.rsplit(".", 1)[-1].lower() if key and "." in key else ""
    return _CONTENT_TYPE.get(ext, "application/octet-stream")


def resolve_root(settings) -> str:
    """The photos root. `contacts_photos_dir` may be absolute or (default)
    relative, in which case it resolves UNDER app_support_dir — never ./data."""
    configured = os.path.expanduser(getattr(settings, "contacts_photos_dir", "contact_photos"))
    if os.path.isabs(configured):
        return configured
    base = os.path.expanduser(getattr(settings, "app_support_dir",
                                      "~/Library/Application Support/ScuffedOS"))
    return os.path.join(base, configured)


def photo_key(store_id: str, source_id: str, ext: str) -> str:
    digest = hashlib.sha256(f"{store_id}:{source_id}".encode()).hexdigest()
    return f"{digest}.{ext}"


def key_for_path(photo_path: str) -> str:
    """The opaque relative key from the reader's transient absolute path. The
    layout is flat, so the key is just the basename (contract: photo_key is
    RELATIVE; the reader's absolute path is converted here, never persisted raw)."""
    return os.path.basename(photo_path)


def _within(root_real: str, candidate_real: str) -> bool:
    return candidate_real == root_real or candidate_real.startswith(root_real + os.sep)


def store_photo(data: bytes, *, store_id: str, source_id: str,
                photos_root: str) -> str | None:
    """Atomically write `data` under photos_root, keyed by sha256(store_id:source_id)
    + the detected extension. Returns the opaque relative key, or None on ANY
    failure (never raises)."""
    detected = detect_media_type(data)
    if detected is None:
        return None
    ext, _ct = detected
    root = os.path.expanduser(photos_root)
    key = photo_key(store_id, source_id, ext)
    try:
        os.makedirs(root, exist_ok=True)
        dst = os.path.join(root, key)
        # containment (the key is machine-generated, but never trust it)
        root_real = os.path.realpath(root)
        if not _within(root_real, os.path.realpath(dst)):
            return None
        fd, tmp = tempfile.mkstemp(prefix=".tmp_photo_", dir=root)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dst)                     # atomic within the same filesystem
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except (OSError, ValueError) as exc:
        logger.warning("contact photo write skipped (%s)", exc.__class__.__name__)
        return None
    return key


def resolve_photo(key: str, photos_root: str) -> str | None:
    """Absolute path for a stored key, or None. Rejects any key whose realpath
    escapes the root (symlink / '..' traversal) and any missing file."""
    if not key:
        return None
    root_real = os.path.realpath(os.path.expanduser(photos_root))
    candidate = os.path.realpath(os.path.join(root_real, key))
    if not _within(root_real, candidate):
        return None
    if not os.path.isfile(candidate):
        return None
    return candidate


def delete_photo(key: str | None, photos_root: str) -> None:
    """Remove one stored photo. Idempotent; never raises (a gone/absent file is
    a no-op). Used when a person is deleted or its photo is superseded."""
    path = resolve_photo(key, photos_root) if key else None
    if path is None:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def cleanup_orphans(keep_keys: set[str], photos_root: str) -> int:
    """Remove every file in photos_root not referenced by keep_keys. Called after
    a successful re-sync, on forget, and on delete. In-flight temp files are left
    alone. Returns the number of files removed."""
    root = os.path.expanduser(photos_root)
    if not os.path.isdir(root):
        return 0
    removed = 0
    for name in os.listdir(root):
        if name in keep_keys or name.startswith(".tmp_photo_"):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        try:
            os.unlink(full)
            removed += 1
        except OSError:
            pass
    return removed
```

- [ ] **Step 4: Run the storage tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contact_photos.py -q`
Expected: PASS (14).

- [ ] **Step 5: Wire the photo pass into the reader** — edit `backend/app/providers/macos_contacts.py`

Add the import beside the existing `from .base import NormalizedPerson`:
```python
from . import contact_photos
```

Add `ZTHUMBNAILIMAGEDATA` to the optional record columns so the blob is fetched only when the store has it:
```python
_RECORD_OPTIONAL = (
    "ZUNIQUEID", "ZFIRSTNAME", "ZLASTNAME", "ZNICKNAME",
    "ZORGANIZATION", "ZJOBTITLE", "ZDISPLAYFLAGS", "ZTHUMBNAILIMAGEDATA",
)
```

Add the thumbnail resolver near `_unwrap_label`:
```python
def _thumbnail_bytes(blob, orig_db_path: str) -> bytes | None:
    """Resolve raw image bytes from a ZTHUMBNAILIMAGEDATA blob. Core Data stores
    either the image (optionally with a 1-byte tag prefix) inline, or a filename
    reference into the store's external-data directory. Best-effort: returns None
    on anything unexpected. External refs are read from the REAL store's _SUPPORT
    dir (read-only), not the private snapshot copy, and the filename is guarded
    against path traversal."""
    if not blob:
        return None
    if contact_photos.detect_media_type(blob) is not None:      # some stores keep raw bytes
        return blob
    tag = blob[0]
    if tag == 1:                                                # inline, 1-byte tag prefix
        body = blob[1:]
        return body if contact_photos.detect_media_type(body) is not None else None
    if tag == 2:                                                # external-data filename ref
        name = blob[1:].split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
        if not name or "/" in name or name.startswith("."):
            return None
        stem = Path(orig_db_path).stem
        support = Path(orig_db_path).parent / f".{stem}_SUPPORT" / "_EXTERNAL_DATA"
        try:
            data = (support / name).read_bytes()
        except OSError:
            return None
        return data if contact_photos.detect_media_type(data) is not None else None
    return None
```

In `_extract_people`, replace the `people.append(...)` block written in Task 4 with a photo pass that precedes it:
```python
        photo_path, has_photo = None, False
        if photos_dir:
            try:
                img = _thumbnail_bytes(col("ZTHUMBNAILIMAGEDATA"), db_path)
                if img is not None:
                    key = contact_photos.store_photo(
                        img, store_id=store_id, source_id=src_id,
                        photos_root=photos_dir)
                    if key:                                     # transient ABSOLUTE path
                        photo_path = os.path.join(os.path.expanduser(photos_dir), key)
                        has_photo = True
            except Exception:                                   # a photo NEVER aborts the read
                logger.warning("contact photo skipped for a record")

        people.append(NormalizedPerson(
            source="macos_contacts",
            source_id=src_id,
            display_name=display,
            first_name=first, last_name=last, nickname=nick,
            organization=org, job_title=job,
            phones=phones, emails=emails,
            photo_path=photo_path, has_photo=has_photo,
            meta={"is_company": is_company, "store_id": store_id,
                  "zuniqueid": uid, "z_pk": z_pk},
        ))
```

> **Where the abs→key conversion happens.** The reader writes the file flat under `photos_dir` (already `contact_photos.resolve_root(settings)` when the sync engine calls it) and sets `NormalizedPerson.photo_path` to the transient *absolute* path. `store.apply_contacts_snapshot` (Task 3) persists `contact_photos.key_for_path(photo_path)` as the opaque, relative `photo_key` — the absolute path is never stored. Writing during the read means a snapshot that later fails to apply (e.g. `PARTIAL_READ`, or a rolled-back transaction) can leave orphan files; those are swept by `cleanup_orphans(keep_keys, ...)` on the next successful sync, on forget, and on delete.

- [ ] **Step 6: Write the reader photo integration test** — `backend/tests/test_macos_contacts_photos.py`

```python
import os
import sqlite3

import pytest

from app.providers import contact_photos
from app.providers.macos_contacts import SnapshotStatus, read_snapshot

_ENT = 19
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _store(path, blob):
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT);"
        "CREATE TABLE ZABCDRECORD (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZUNIQUEID TEXT,"
        " ZFIRSTNAME TEXT, ZLASTNAME TEXT, ZNICKNAME TEXT, ZORGANIZATION TEXT, ZJOBTITLE TEXT,"
        " ZDISPLAYFLAGS INTEGER, ZTHUMBNAILIMAGEDATA BLOB);"
        "CREATE TABLE ZABCDPHONENUMBER (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,"
        " ZFULLNUMBER TEXT, ZLABEL TEXT, ZORDERINGINDEX INTEGER);"
        "CREATE TABLE ZABCDEMAILADDRESS (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,"
        " ZADDRESS TEXT, ZLABEL TEXT, ZORDERINGINDEX INTEGER);"
    )
    con.execute("INSERT INTO Z_PRIMARYKEY VALUES (?, 'ABCDContact')", (_ENT,))
    con.execute(
        "INSERT INTO ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZDISPLAYFLAGS,"
        " ZTHUMBNAILIMAGEDATA) VALUES (1, ?, 'UID-P:ABPerson', 'Pic', 0, ?)", (_ENT, blob))
    con.commit()
    con.close()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "AddressBook"
    r.mkdir()
    return r


def test_inline_tagged_photo_extracted(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + _PNG)     # 1-byte inline tag
    photos = tmp_path / "photos"
    snap = read_snapshot(str(root), region="US", photos_dir=str(photos))
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    p = snap.people[0]
    assert p.has_photo is True
    assert p.photo_path and p.photo_path.endswith(".png")           # transient ABSOLUTE path
    assert os.path.isfile(p.photo_path)
    key = contact_photos.key_for_path(p.photo_path)
    assert contact_photos.resolve_photo(key, str(photos)) is not None


def test_raw_untagged_photo_extracted(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), _PNG)              # raw, no tag prefix
    snap = read_snapshot(str(root), region="US", photos_dir=str(tmp_path / "photos"))
    assert snap.people[0].has_photo is True


def test_person_without_thumbnail_has_no_photo(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), None)              # NULL blob
    snap = read_snapshot(str(root), region="US", photos_dir=str(tmp_path / "photos"))
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.people[0].has_photo is False
    assert snap.people[0].photo_path is None


def test_malformed_blob_imports_person_without_photo(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + b"not an image")
    snap = read_snapshot(str(root), region="US", photos_dir=str(tmp_path / "photos"))
    # the person is STILL imported and the snapshot stays COMPLETE — a bad photo
    # never aborts the read
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.people[0].has_photo is False


def test_photos_dir_none_skips_extraction(root, tmp_path):
    _store(str(root / "AddressBook-v22.abcddb"), b"\x01" + _PNG)
    snap = read_snapshot(str(root), region="US", photos_dir=None)
    assert snap.people[0].has_photo is False
```

- [ ] **Step 7: Run the photo tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_macos_contacts_photos.py tests/test_contact_photos.py tests/test_macos_contacts_reader.py -q`
Expected: PASS — the 5 reader-photo tests, the 14 storage tests, and the 19 Task-4 reader tests all green (the reader edits are additive; Task-4 tests pass `photos_dir=None` and are unaffected).

- [ ] **Step 8: Full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` (report the count; expect **+19** over Task 4 — 14 storage + 5 reader-photo)
```bash
git add backend/app/providers/contact_photos.py backend/app/providers/macos_contacts.py \
  backend/tests/test_contact_photos.py backend/tests/test_macos_contacts_photos.py
git commit -m "feat(people): contact photo storage (magic-byte type, atomic write, containment, cleanup) + reader photo pass (M10 s1)"
```

---

---

## Task 6 — Sync engine (`contacts_sync.py`)

The token-less, consent-gated pass. It reads the local AddressBook via
`read_snapshot()` (Task 5), delegates the transactional write to
`store.apply_contacts_snapshot()` (Task 3), and returns a `SyncResult`. It is a
**no-op when contacts consent is off**, it **never crashes**, and an
**unreachable/erroring PostgreSQL server is a FAILED sync (`status='error'`),
never an empty one** — so a remote-DB blip can never masquerade as "every
contact was deleted". Manual `POST /sync` and the background loop both run
through the same `tick()` → `apply_contacts_snapshot()` path, which the store
serializes under its process + advisory lock.

**Files:**
- Create: `backend/app/contacts_sync.py`
- Modify: `backend/app/db.py` (add `_assert_secure_dsn` + wire it into `make_engine`)
- Modify: `backend/app/main.py` (import + lifespan task + shutdown tuple)
- Create: `backend/tests/test_contacts_sync.py`
- Create: `backend/tests/test_db_dsn.py`
- (Reuses `store.get_contacts_state()` from Task 3 — this task does NOT re-add it.)

**Interfaces:**
- Consumes:
  - `macos_contacts.read_snapshot(root=DEFAULT_ROOT, *, region: str, photos_dir: str, enabled: bool = True) -> ContactsSnapshot` and `ContactsSnapshot`/`SnapshotStatus` (Task 5) — classifies, never raises for control flow.
  - `store.apply_contacts_snapshot(snapshot, now) -> SyncResult` and the `SyncResult` dataclass (Task 3); the store owns locking + reconciliation.
  - `ContactsSyncState` ORM model (Task 2); `settings.contacts_sync_enabled` / `contacts_sync_seconds` / `contacts_default_region` / `contacts_photos_root()` (all added to `config.py` in Task 3).
- Produces:
  - `contacts_sync.tick(now: datetime | None = None) -> SyncResult`
  - `async trigger() -> SyncResult`
  - `async run_loop() -> None`
  - `configure(override="unset") -> None`
  - `_assert_secure_dsn(url: str) -> None` in `backend/app/db.py`, wired into `make_engine` (TLS required for non-loopback PostgreSQL).
  - (Consumes `store.get_contacts_state() -> dict` — defined in Task 3, NOT redefined here.)

- [ ] **Step 1: Reuse the store's consent-state reader (from Task 3)**

`store.get_contacts_state()` and the module-level `_state_dict(st)` serializer are
already defined in **Task 3** (the consent get/set helpers), and `_state_row`
read-or-creates the single `contacts_sync_state` row (consent `enabled` defaults
OFF — no probing/reads until the user explicitly connects). **Do NOT redefine
`get_contacts_state` (or a second `_contacts_state_dict`) here** — a duplicate
method on `Store` would silently shadow Task 3's. This task only consumes the
existing method; the sync engine reads consent through `store.get_contacts_state()`.

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
from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus
from app.store import SyncResult, store


@pytest.fixture(autouse=True)
def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    store.configure(sessionmaker(eng))
    yield
    store.configure(None)
    contacts_sync.configure("unset")


def _snap(status, people=()):
    return ContactsSnapshot(status=status, people=list(people),
                            stores_total=1, stores_read=1, store_ids=["local"])


def test_default_state_is_disabled_noop(monkeypatch):
    # Consent defaults OFF: tick must NOT touch the AddressBook at all.
    def must_not_read(*a, **k):
        raise AssertionError("read_snapshot must not run while consent is off")

    monkeypatch.setattr(macos_contacts, "read_snapshot", must_not_read)
    result = contacts_sync.tick()
    assert result.status == "disabled"


def test_complete_snapshot_delegates_to_apply(monkeypatch):
    monkeypatch.setattr(store, "get_contacts_state", lambda: {
        "enabled": True, "normalization_region": "US", "access": "granted",
        "last_sync_at": None,
    })
    snap = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [NormalizedPerson(source="macos_contacts", source_id="A", display_name="A")])
    monkeypatch.setattr(macos_contacts, "read_snapshot", lambda *a, **k: snap)
    seen = {}

    def fake_apply(snapshot, now):
        seen["snapshot"] = snapshot
        seen["now"] = now
        return SyncResult(status="ok", access="granted", imported=1,
                          updated=0, removed=0, last_sync_at=now)

    monkeypatch.setattr(store, "apply_contacts_snapshot", fake_apply)
    result = contacts_sync.tick()
    assert result.status == "ok"
    assert result.imported == 1
    assert seen["snapshot"] is snap             # the reader's snapshot, applied verbatim


def test_unreachable_database_is_error_never_empty(monkeypatch):
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr(store, "get_contacts_state", lambda: {
        "enabled": True, "normalization_region": "US", "access": "granted",
        "last_sync_at": None,
    })
    monkeypatch.setattr(macos_contacts, "read_snapshot",
                        lambda *a, **k: _snap(SnapshotStatus.COMPLETE_EMPTY))

    def db_down(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("could not connect to server"))

    monkeypatch.setattr(store, "apply_contacts_snapshot", db_down)
    result = contacts_sync.tick()
    assert result.status == "error"             # a failed remote DB is a FAILED sync
    assert result.status != "empty"             # never mistaken for an empty source


def test_state_read_failure_is_error_and_never_crashes(monkeypatch):
    def db_down():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(store, "get_contacts_state", db_down)
    result = contacts_sync.tick()               # must not raise
    assert result.status == "error"


def test_access_denied_snapshot_flows_through_apply(monkeypatch):
    monkeypatch.setattr(store, "get_contacts_state", lambda: {
        "enabled": True, "normalization_region": "US", "access": "granted",
        "last_sync_at": None,
    })
    monkeypatch.setattr(macos_contacts, "read_snapshot",
                        lambda *a, **k: _snap(SnapshotStatus.ACCESS_DENIED))

    def fake_apply(snapshot, now):
        assert snapshot.status == SnapshotStatus.ACCESS_DENIED
        return SyncResult(status="access_denied", access="denied")

    monkeypatch.setattr(store, "apply_contacts_snapshot", fake_apply)
    result = contacts_sync.tick()
    assert result.status == "access_denied"
    assert result.access == "denied"


def test_configure_override():
    class Fake:
        def tick(self, now=None):
            return SyncResult(status="ok", access="granted", imported=99)

    contacts_sync.configure(Fake())
    assert contacts_sync.tick().imported == 99
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contacts_sync.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.contacts_sync'`

- [ ] **Step 4: Write the sync engine** — `backend/app/contacts_sync.py`

```python
"""Contacts sync engine (M10 s1) — a token-less, consent-gated pass.

Reads the local macOS AddressBook via providers.macos_contacts.read_snapshot()
(no network, no OAuth, no cursor) and hands the resulting ContactsSnapshot to
store.apply_contacts_snapshot(), which does the whole transactional write
(upsert + handle re-index + reconcile) under its process + advisory lock. This
module only orchestrates; the store owns locking and reconciliation safety.

Invariants:
  * Consent-gated: while contacts_sync_state.enabled is False, tick() is a pure
    no-op — it reads NOTHING from the AddressBook and returns status='disabled'.
  * Never crashes: every failure is caught and turned into a SyncResult.
  * An unreachable / erroring PostgreSQL server (structured contact data is
    persisted to the configured database, which may be remote/self-hosted) is a
    FAILED sync (status='error') — NEVER an 'empty' one. A DB blip must not look
    like "every contact vanished".

Test seam: configure(fake) installs an object whose .tick() this delegates to;
configure(None)/"unset" runs the real pass.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import settings
from .providers import macos_contacts
from .providers.macos_contacts import ContactsSnapshot, SnapshotStatus
from .store import SyncResult, store

logger = logging.getLogger("scuffed_os.contacts_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _access_for(snapshot: ContactsSnapshot) -> str:
    if snapshot.status in (SnapshotStatus.COMPLETE_NONEMPTY, SnapshotStatus.COMPLETE_EMPTY):
        return "granted"
    if snapshot.status == SnapshotStatus.ACCESS_DENIED:
        return "denied"
    return "unknown"


def tick(now: datetime | None = None) -> SyncResult:
    """One contacts pass. Returns a SyncResult; never raises.

    - consent off            -> status='disabled', zero reads
    - snapshot not COMPLETE_* -> the store records the status; no row writes
    - DB unreachable          -> status='error' (never 'empty')
    """
    if _override not in ("unset", None) and hasattr(_override, "tick"):
        return _override.tick(now)  # type: ignore[union-attr]

    now = now or _utcnow()

    # 1) Consent gate. A DB failure reading the flag is itself a failed sync.
    try:
        state = store.get_contacts_state()
    except Exception:
        logger.exception("contacts sync: could not read consent state (database unavailable?)")
        return SyncResult(status="error", access="unknown",
                          last_error="database unavailable")
    if not state.get("enabled"):
        return SyncResult(status="disabled", access=state.get("access", "unknown"),
                          last_sync_at=state.get("last_sync_at"))

    # 2) Read the local AddressBook. read_snapshot() classifies rather than
    #    raising; guard anyway so a reader bug can never crash the loop.
    region = state.get("normalization_region") or settings.contacts_default_region
    try:
        snapshot = macos_contacts.read_snapshot(
            getattr(settings, "addressbook_root", macos_contacts.DEFAULT_ROOT),
            region=region,
            photos_dir=settings.contacts_photos_root(),
            enabled=True,
        )
    except Exception:
        logger.exception("contacts sync: read_snapshot crashed")
        snapshot = ContactsSnapshot(status=SnapshotStatus.IO_ERROR, people=[],
                                    error="reader failed")

    # 3) Apply. The store serializes this under its process + advisory lock, so
    #    manual /sync and the background loop can never interleave a write.
    try:
        return store.apply_contacts_snapshot(snapshot, now)
    except Exception:
        logger.exception("contacts sync: apply_contacts_snapshot failed (database unavailable?)")
        return SyncResult(status="error", access=_access_for(snapshot),
                          last_error="database unavailable during sync")


async def trigger() -> SyncResult:
    """Run one pass off the event loop. Awaited by POST /api/people/sync and by
    the enable endpoint's first-sync kick."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    """Background loop. Gated by settings.contacts_sync_enabled (started only when
    true) AND, per tick, by contacts_sync_state.enabled (tick() no-ops when off)."""
    logger.info("contacts sync loop started (every %ss)", settings.contacts_sync_seconds)
    while True:
        try:
            if settings.contacts_sync_enabled:
                result = await asyncio.to_thread(tick)
                if result.status == "ok" and (result.imported or result.updated or result.removed):
                    logger.info("contacts sync: +%d ~%d -%d",
                                result.imported, result.updated, result.removed)
        except Exception:
            logger.exception("contacts sync tick failed")
        await asyncio.sleep(settings.contacts_sync_seconds)
```

- [ ] **Step 5: Wire the lifespan** — `backend/app/main.py`

- Add `contacts_sync` to the top-level `from . import ...` that already imports `moodle_sync` (grep `moodle_sync` in main.py's imports).
- In `lifespan`, after `finance_task: asyncio.Task | None = None` add:
```python
    contacts_task: asyncio.Task | None = None
```
- After the `if settings.finance_sync_enabled:` block add:
```python
    if settings.contacts_sync_enabled:
        contacts_task = asyncio.create_task(contacts_sync.run_loop())
```
- Add `contacts_task` to the shutdown tuple:
```python
    for task in (reminder_task, fitness_task, email_task, moodle_task, finance_task, contacts_task):
```

- [ ] **Step 6: TLS guard for non-loopback DSNs** — `backend/app/db.py`

Structured contact data (and all app data) is persisted to the configured
PostgreSQL database, which **may be remote/self-hosted**. Remote DSNs are
**supported** — only an *insecure* (non-TLS) non-loopback DSN is rejected. The
guard is described in prose in Task 7 §8 but is **implemented here**. Never log
the DSN or credentials (redacted host only).

Add near the top of `backend/app/db.py`:
```python
def _assert_secure_dsn(url: str) -> None:
    """Reject a non-loopback PostgreSQL DSN that lacks TLS. Loopback needs no TLS;
    a remote host requires sslmode=require|verify-ca|verify-full. Remote DSNs are
    SUPPORTED — only insecure ones are refused. The error text carries a redacted
    host only, NEVER the DSN or password."""
    from sqlalchemy.engine import make_url

    u = make_url(url)
    host = (u.host or "").lower()
    is_loopback = host in ("", "localhost", "127.0.0.1", "::1")
    if u.drivername.startswith("postgresql") and not is_loopback:
        sslmode = (u.query.get("sslmode") or "").lower()
        if sslmode not in ("require", "verify-ca", "verify-full"):
            raise RuntimeError(
                f"Refusing a non-loopback PostgreSQL DSN without TLS (host={host!r}); "
                "set sslmode=require or stronger."
            )
```
Wire it into `make_engine` **after** the URL is normalized (so a raw `postgres://`
scheme is already `postgresql+psycopg://` and the check sees it) and **before**
`create_engine(...)` — the check is lazy and opens no connection:
```python
    url = normalize_database_url(raw_url)
    _assert_secure_dsn(url)
```

Write the test — `backend/tests/test_db_dsn.py`:
```python
import pytest

from app.db import make_engine, normalize_database_url


def test_loopback_and_sqlite_need_no_tls():
    for dsn in ("postgresql://u:p@127.0.0.1:5432/app",
                "postgresql://u:p@localhost/app",
                "sqlite://"):
        eng = make_engine(dsn)
        eng.dispose()


def test_remote_dsn_with_tls_is_accepted():
    eng = make_engine("postgresql://u:secret@db.example.com:5432/app?sslmode=require")
    try:
        assert eng.dialect.name == "postgresql"
    finally:
        eng.dispose()


def test_remote_dsn_without_tls_is_rejected():
    with pytest.raises(RuntimeError) as exc:
        make_engine("postgresql://u:secret@db.example.com:5432/app")
    # names the problem but never leaks the password
    assert "secret" not in str(exc.value)
    assert "TLS" in str(exc.value) or "sslmode" in str(exc.value)


def test_normalize_keeps_remote_host_and_scheme():
    assert normalize_database_url(
        "postgres://u:p@10.0.0.9:5432/app?sslmode=require"
    ).startswith("postgresql+psycopg://")
```

Run: `cd backend && .venv/bin/python -m pytest tests/test_db_dsn.py -q`
Expected: PASS (4). Remote DSNs are accepted **with** TLS and refused only
**without** it; no test asserts a remote DSN is refused outright (if a prior
revision added such a test, delete it).

- [ ] **Step 7: Run the sync + DSN tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contacts_sync.py tests/test_db_dsn.py -q`
Expected: PASS (11 — 7 sync + 4 DSN)

- [ ] **Step 8: Full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` (report the count; baseline = 703 collected)
```bash
git add backend/app/contacts_sync.py backend/app/db.py backend/app/main.py backend/tests/test_contacts_sync.py backend/tests/test_db_dsn.py
git commit -m "feat(people): consent-gated token-less contacts sync engine (disabled no-op, DB-down=error, shared lock) + lifespan wiring + non-loopback TLS DSN guard (M10 s1)"
```

---

## Task 7 — People router + typed schemas + consent endpoints + photo endpoint + `api.js`

Source-aware CRUD, the three consent endpoints (`enable` / `disconnect` /
`forget`), the containment-checked photo endpoint, and the frontend client
methods. Imported (`source='macos_contacts'`) identity is **read-only** through
the API — you edit it in Apple Contacts; only the ScuffedOS-owned CRM-native
fields are writable on an imported row. `forget` honors the **CRM-native
survival rule** (a person carrying CRM data is converted to a `manual`
tombstone, not deleted).

**Files:**
- Modify: `backend/app/schemas.py` (typed `PhoneEntry`/`EmailEntry` + `PersonOut/Create/Update` + `PeoplePage` + `SyncResultOut` + `ContactsStateOut` + request bodies)
- Modify: `backend/app/store.py` (`enable_contacts`, `disconnect_contacts`, `forget_contacts`, `get_person_photo_key` + the `_delete_photo_files` helper; the paginated list reuses Task 3's `list_people`)
- Create: `backend/app/routers/people.py`
- Modify: `backend/app/main.py` (router import + include)
- Modify: `frontend/src/lib/api.js`
- Create: `backend/tests/test_people_api.py`

**Interfaces:**
- Consumes: `store.list_people/get_person/create_person/update_person/delete_person/resolve_handle` (Task 3); `store.get_contacts_state` (Task 3); `store.apply_contacts_snapshot` indirectly via `contacts_sync.tick` (Task 6); `settings.contacts_default_region` / `settings.contacts_photos_root()` (config, Task 3).
- Produces: REST `GET/POST /api/people`, `GET/PATCH/DELETE /api/people/{id}`, `POST /api/people/sync -> SyncResult`, `POST /api/people/contacts/{enable,disconnect,forget}`, `GET /api/people/{id}/photo`; `PersonOut/Create/Update` (typed `PhoneEntry`/`EmailEntry`); `store.enable_contacts/disconnect_contacts/forget_contacts/get_person_photo_key` (the list endpoint reuses Task 3's `list_people`); `api.listPeople/getPerson/createPerson/updatePerson/deletePerson/syncContacts/enableContacts/disconnectContacts/forgetContacts/personPhotoUrl`.

- [ ] **Step 1: Add the typed schemas** — `backend/app/schemas.py` (after the Memory block; `BaseModel`, `Field`, `datetime`, `Literal` already imported)

```python
# ---- People (M10) ---------------------------------------------------------
class PhoneEntry(BaseModel):
    value: str = Field(min_length=1)
    label: str = ""
    normalized: str | None = None


class EmailEntry(BaseModel):
    value: str = Field(min_length=1)
    label: str = ""
    normalized: str | None = None


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
    phones: list[PhoneEntry]
    emails: list[EmailEntry]
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
    first_name: str = ""
    last_name: str = ""
    nickname: str = ""
    organization: str = ""
    job_title: str = ""
    phones: list[PhoneEntry] = []
    emails: list[EmailEntry] = []
    relationship: str | None = None
    relationship_strength: int | None = None
    notes: str | None = None
    pinned: bool = False


class PersonUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    nickname: str | None = None
    organization: str | None = None
    job_title: str | None = None
    phones: list[PhoneEntry] | None = None
    emails: list[EmailEntry] | None = None
    relationship: str | None = None
    relationship_strength: int | None = None
    notes: str | None = None
    pinned: bool | None = None
    last_contacted_at: datetime | None = None


class PeoplePage(BaseModel):
    items: list[PersonOut]
    next_cursor: str | None = None


class SyncResultOut(BaseModel):
    status: str
    access: str
    imported: int = 0
    updated: int = 0
    removed: int = 0
    last_sync_at: datetime | None = None
    last_error: str | None = None


class ContactsStateOut(BaseModel):
    enabled: bool
    status: str
    access: str
    normalization_region: str | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None
    enabled_at: datetime | None = None


class ContactsEnableIn(BaseModel):
    ack_storage_disclosure: bool = False


class ContactsForgetIn(BaseModel):
    confirm: bool = False
```

- [ ] **Step 2: Add the store methods the router needs** — `backend/app/store.py`

Extend the top imports: `from sqlalchemy import and_, func, or_, select` (add `and_`, `func`, `or_` to the existing `select` import). The keyset-cursor codec (`_encode_cursor`/`_decode_cursor`) is **already defined in Task 3** — reuse it, do NOT redefine it here. Add only the module-level photo-cleanup helper near `_state_dict`:

```python
def _delete_photo_files(photos_root: str, keys: list[str]) -> None:
    """Best-effort unlink of relative photo_key files under the resolved photos
    root, with a containment check (never follow `..`/symlinks out of the root).
    A failure here never aborts the calling operation."""
    real_root = os.path.realpath(photos_root)
    for key in keys:
        if not key:
            continue
        target = os.path.realpath(os.path.join(real_root, key))
        try:
            if os.path.commonpath([real_root, target]) == real_root and os.path.isfile(target):
                os.remove(target)
        except (OSError, ValueError):
            pass
```

(Ensure `import os` is present at the top of `store.py`.) In class `Store`, after `get_contacts_state` (Task 6):

```python
    # ---- people photo key (M10) ----
    # NOTE: the paginated/searchable people list is `store.list_people(...)` from
    # Task 3 (same `{items, next_cursor}` shape, and it searches
    # name/nickname/organization/job_title). The router calls it directly; do NOT
    # add a second `search_people` here.
    def get_person_photo_key(self, person_id: int) -> str | None:
        """The relative photo_key (opaque, stored in the configured database), or
        None. The router resolves it against the photos root with a containment
        check; the key itself is never a filesystem path we trust blindly."""
        from .config import settings

        with self._session() as s:
            row = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.id == person_id)
            ).first()
            return row.photo_key if row is not None else None

    # ---- contacts consent lifecycle (M10) ----
    def enable_contacts(self, *, region: str) -> dict:
        """Connect: enabled=True, stamp enabled_at, and persist normalization_region
        ONCE (a later locale change must never retroactively re-resolve existing
        handles). Does not read contacts here — the caller kicks a sync."""
        from .config import settings

        with self._session() as s, s.begin():
            row = s.scalars(
                select(ContactsSyncState).where(ContactsSyncState.owner == settings.owner)
            ).first()
            if row is None:
                row = ContactsSyncState(owner=settings.owner)
                s.add(row)
            row.enabled = True
            row.enabled_at = datetime.now(timezone.utc)
            if not row.normalization_region:
                row.normalization_region = region
            if row.status in (None, "disabled"):
                row.status = "ready"
            s.flush()
            return _state_dict(row)   # Task 3's serializer (single state-dict helper)

    def disconnect_contacts(self) -> dict:
        """Disconnect: stop future reads/syncs. Does NOT delete rows — existing CRM
        data is preserved; normalization_region is kept."""
        from .config import settings

        with self._session() as s, s.begin():
            row = s.scalars(
                select(ContactsSyncState).where(ContactsSyncState.owner == settings.owner)
            ).first()
            if row is None:
                row = ContactsSyncState(owner=settings.owner)
                s.add(row)
            row.enabled = False
            row.status = "disabled"
            s.flush()
            return _state_dict(row)   # Task 3's serializer (single state-dict helper)

    @_retry_integrity
    def forget_contacts(self) -> dict:
        """Delete imported (source='macos_contacts') rows + their handle rows +
        extracted photos, then disable. CRM-native survival rule: a person carrying
        ANY CRM-native data (relationship/strength/notes/pinned/last_contacted_at)
        is converted to a source='manual' tombstone that keeps display_name + the
        CRM-native fields (identity fields, handle index and photo cleared);
        people with no CRM-native data are fully deleted."""
        import uuid

        from .config import settings

        photos_root = settings.contacts_photos_root()
        removed_keys: list[str] = []
        with self._session() as s, s.begin():
            rows = s.scalars(
                select(Person)
                .where(Person.owner == settings.owner)
                .where(Person.source == "macos_contacts")
            ).all()
            for row in rows:
                if row.photo_key:
                    removed_keys.append(row.photo_key)
                has_crm = any((row.relationship, row.relationship_strength, row.notes,
                               row.pinned, row.last_contacted_at))
                if has_crm:
                    s.query(PersonHandle).filter(PersonHandle.person_id == row.id).delete()
                    row.source = "manual"
                    row.source_id = uuid.uuid4().hex
                    row.first_name = ""
                    row.last_name = ""
                    row.nickname = ""
                    row.organization = ""
                    row.job_title = ""
                    row.phones = []
                    row.emails = []
                    row.photo_key = None
                    row.has_photo = False
                    row.removed_from_source_at = None
                else:
                    s.delete(row)  # person_handle rows cascade
            state = s.scalars(
                select(ContactsSyncState).where(ContactsSyncState.owner == settings.owner)
            ).first()
            if state is None:
                state = ContactsSyncState(owner=settings.owner)
                s.add(state)
            state.enabled = False
            state.status = "disabled"
            state.last_error = None
            s.flush()
            result = _state_dict(state)   # Task 3's serializer (single state-dict helper)
        _delete_photo_files(photos_root, removed_keys)   # after commit; never fatal
        return result
```

- [ ] **Step 3: Write the failing test** — `backend/tests/test_people_api.py`

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.main import app
from app.models import Person
from app.store import store


@pytest.fixture(autouse=True)
def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    store.configure(sessionmaker(eng))
    yield
    store.configure(None)


def _insert_imported(**over):
    fields = dict(owner=settings.owner, source="macos_contacts", source_id="src-1",
                  display_name="Imported Person", phones=[], emails=[], meta={})
    fields.update(over)
    with store._session() as s, s.begin():
        row = Person(**fields)
        s.add(row)
        s.flush()
        return row.id


def test_manual_crud_roundtrip():
    c = TestClient(app)
    assert c.get("/api/people").json() == {"items": [], "next_cursor": None}
    created = c.post("/api/people", json={"display_name": "Ada Lovelace"}).json()
    assert created["source"] == "manual"
    pid = created["id"]
    patched = c.patch(f"/api/people/{pid}", json={"relationship": "Friend"}).json()
    assert patched["relationship"] == "Friend"
    assert c.get(f"/api/people/{pid}").json()["display_name"] == "Ada Lovelace"
    assert c.delete(f"/api/people/{pid}").status_code == 204
    assert c.get(f"/api/people/{pid}").status_code == 404


def test_imported_identity_is_read_only_but_crm_native_editable():
    c = TestClient(app)
    pid = _insert_imported()
    # identity edit rejected...
    assert c.patch(f"/api/people/{pid}", json={"display_name": "Hacked"}).status_code == 409
    assert c.patch(f"/api/people/{pid}", json={"emails": [{"value": "x@y.com"}]}).status_code == 409
    # ...CRM-native edit allowed
    ok = c.patch(f"/api/people/{pid}", json={"pinned": True, "notes": "met at PyCon"})
    assert ok.status_code == 200
    assert ok.json()["pinned"] is True
    # imported rows can't be hard-deleted individually
    assert c.delete(f"/api/people/{pid}").status_code == 409


def test_list_pagination_and_search():
    c = TestClient(app)
    for name in ("Al", "Bo", "Cy", "Di"):
        c.post("/api/people", json={"display_name": name})
    page1 = c.get("/api/people", params={"limit": 2}).json()
    assert [p["display_name"] for p in page1["items"]] == ["Al", "Bo"]
    assert page1["next_cursor"]
    page2 = c.get("/api/people", params={"limit": 2, "cursor": page1["next_cursor"]}).json()
    assert [p["display_name"] for p in page2["items"]] == ["Cy", "Di"]
    assert page2["next_cursor"] is None
    hit = c.get("/api/people", params={"q": "cy"}).json()
    assert [p["display_name"] for p in hit["items"]] == ["Cy"]


def test_sync_endpoint_returns_syncresult_shape(monkeypatch):
    from app import contacts_sync
    from app.store import SyncResult

    monkeypatch.setattr(contacts_sync, "tick",
                        lambda now=None: SyncResult(status="ok", access="granted",
                                                    imported=3, updated=1, removed=0))
    body = TestClient(app).post("/api/people/sync").json()
    assert body["status"] == "ok"
    assert body["access"] == "granted"
    assert body["imported"] == 3 and body["updated"] == 1


def test_enable_requires_ack_then_kicks_sync(monkeypatch):
    from app import contacts_sync
    from app.store import SyncResult

    called = {"n": 0}

    def fake_tick(now=None):
        called["n"] += 1
        return SyncResult(status="ok", access="granted")

    monkeypatch.setattr(contacts_sync, "tick", fake_tick)
    c = TestClient(app)
    assert c.post("/api/people/contacts/enable", json={}).status_code == 400  # no ack
    body = c.post("/api/people/contacts/enable",
                  json={"ack_storage_disclosure": True}).json()
    assert body["enabled"] is True
    assert body["normalization_region"] == settings.contacts_default_region
    assert called["n"] == 1                                                  # sync kicked


def test_disconnect_preserves_rows():
    c = TestClient(app)
    _insert_imported()
    body = c.post("/api/people/contacts/disconnect").json()
    assert body["enabled"] is False
    assert body["status"] == "disabled"
    assert len(c.get("/api/people").json()["items"]) == 1                    # row kept


def test_forget_requires_confirm_and_applies_tombstone_rule():
    c = TestClient(app)
    keep = _insert_imported(source_id="keep", display_name="Has CRM", notes="best man")
    drop = _insert_imported(source_id="drop", display_name="No CRM")
    assert c.post("/api/people/contacts/forget", json={}).status_code == 400  # no confirm
    c.post("/api/people/contacts/forget", json={"confirm": True})
    kept = c.get(f"/api/people/{keep}").json()
    assert kept["source"] == "manual"           # converted to a tombstone
    assert kept["display_name"] == "Has CRM"
    assert kept["notes"] == "best man"
    assert c.get(f"/api/people/{drop}").status_code == 404   # fully deleted


def test_photo_endpoint_serves_detected_type_and_guards_traversal(monkeypatch, tmp_path):
    photos = tmp_path / "contact_photos"
    photos.mkdir()
    monkeypatch.setattr(settings, "contacts_photos_root", lambda: str(photos))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    (photos / "pic.png").write_bytes(png)
    c = TestClient(app)
    pid = _insert_imported(photo_key="pic.png", has_photo=True)
    r = c.get(f"/api/people/{pid}/photo")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # missing key -> 404
    nokey = _insert_imported(source_id="np", photo_key=None)
    assert c.get(f"/api/people/{nokey}/photo").status_code == 404
    # traversal attempt -> 404 (containment check)
    evil = _insert_imported(source_id="ev", photo_key="../secret.png", has_photo=True)
    (tmp_path / "secret.png").write_bytes(png)
    assert c.get(f"/api/people/{evil}/photo").status_code == 404
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_people_api.py -q`
Expected: FAIL — 404 on `/api/people` (router not registered).

- [ ] **Step 5: Write the router** — `backend/app/routers/people.py`

```python
"""People CRUD + macOS Contacts consent lifecycle (M10 s1).

Structured contact fields (names, phones, emails, org/title, handle index) are
persisted to the configured PostgreSQL database (which may run locally or on a
remote/self-hosted server). Imported (source='macos_contacts') identity is
read-only through this API — edit it in Apple Contacts; only the ScuffedOS-owned
CRM-native fields are writable on an imported row. Extracted photos live on the
backend host's filesystem and are served by relative key with a containment
check."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse

from .. import contacts_sync
from ..config import settings
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
    return store.create_person(body.model_dump())


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


def _detect_media_type(head: bytes) -> str | None:
    """Real media type from magic bytes (never trust the stored extension)."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"heis", b"hevc", b"mif1"):
        return "image/heic"
    return None


@router.get("/{person_id}/photo")
def get_person_photo(person_id: int) -> FileResponse:
    key = store.get_person_photo_key(person_id)
    if not key:
        raise HTTPException(status_code=404, detail="No photo")
    root = os.path.realpath(settings.contacts_photos_root())
    target = os.path.realpath(os.path.join(root, key))
    try:
        contained = os.path.commonpath([root, target]) == root
    except ValueError:
        contained = False   # different drive/root -> reject
    if not contained or not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="No photo")
    with open(target, "rb") as fh:
        head = fh.read(16)
    media_type = _detect_media_type(head)
    if media_type is None:
        raise HTTPException(status_code=404, detail="No photo")
    return FileResponse(target, media_type=media_type)
```

- [ ] **Step 6: Register the router** — `backend/app/main.py`

- Add `people,` to the `from .routers import (...)` tuple (alphabetically after `oauth,`).
- Add `app.include_router(people.router)` after `app.include_router(memory.router)`.

- [ ] **Step 7: Add the `api.js` methods** — `frontend/src/lib/api.js` (after the memories block; `personPhotoUrl` uses the module's configured `BASE`, the same base `request()` prepends and that `setApiBase()` sets in the packaged app)

```js
  // People / CRM (M10) — real contact rows (macOS Contacts sync + manual).
  listPeople: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.cursor) qs.set('cursor', params.cursor)
    if (params.limit != null) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request(`/api/people${suffix}`)
  },
  getPerson: (id) => request(`/api/people/${id}`),
  createPerson: (person) => request('/api/people', {
    method: 'POST',
    body: JSON.stringify(typeof person === 'string' ? { display_name: person } : person),
  }),
  updatePerson: (id, patch) => request(`/api/people/${id}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  }),
  deletePerson: (id) => request(`/api/people/${id}`, { method: 'DELETE' }),
  syncContacts: () => request('/api/people/sync', { method: 'POST' }),
  enableContacts: (ack = true) => request('/api/people/contacts/enable', {
    method: 'POST', body: JSON.stringify({ ack_storage_disclosure: ack }),
  }),
  disconnectContacts: () => request('/api/people/contacts/disconnect', { method: 'POST' }),
  forgetContacts: () => request('/api/people/contacts/forget', {
    method: 'POST', body: JSON.stringify({ confirm: true }),
  }),
  // Absolute URL for an <img src>; resolves against the configured API base.
  personPhotoUrl: (id) => `${BASE}/api/people/${id}/photo`,
```

- [ ] **Step 8: Persistence hardening note (TLS + no-secrets-in-logs)**

The People slice persists structured contact data to the configured PostgreSQL
database, which **may be remote/self-hosted**; when it is remote, contact data
travels over the network to that server. The two guarantees below live in the
**config/db layer (`backend/app/db.py`, implemented in Task 6)**, not in this
router — the router and sync engine merely rely on them and **never log a DSN or
credentials**:

- **TLS is required for any non-loopback DSN.** The engine builder in
  `backend/app/db.py` refuses a non-loopback PostgreSQL DSN without
  `sslmode=require` (or stronger). Remote DSNs themselves are **supported and
  must not be rejected** — only insecure ones are. For reference, the guard
  (implemented + tested in **Task 6**) is:

  ```python
  # backend/app/db.py — added in Task 6; restated here so the People router's
  # persistence guarantee is explicit. NEVER log `url`; log a redacted host only.
  def _assert_secure_dsn(url: str) -> None:
      from sqlalchemy.engine import make_url

      u = make_url(url)
      host = (u.host or "").lower()
      is_loopback = host in ("", "localhost", "127.0.0.1", "::1")
      if u.drivername.startswith("postgresql") and not is_loopback:
          sslmode = (u.query.get("sslmode") or "").lower()
          if sslmode not in ("require", "verify-ca", "verify-full"):
              raise RuntimeError(
                  f"Refusing a non-loopback PostgreSQL DSN without TLS (host={host!r}); "
                  "set sslmode=require or stronger."
              )
  ```

- The matching tests (**a remote DSN with TLS is accepted**, an insecure remote
  DSN is rejected, a loopback DSN needs no TLS) live in **Task 6's**
  `tests/test_db_dsn.py`; there is intentionally **no remote-DSN-refusal test**
  (remote DSNs are supported — only insecure non-loopback ones are rejected). No
  new code is added in this task for the guard — this step is the cross-reference
  so the router's persistence contract is auditable in one place.

- [ ] **Step 9: Run the api tests + full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_people_api.py -q` then `.venv/bin/python -m pytest -q` (report the count)
```bash
git add backend/app/routers/people.py backend/app/schemas.py backend/app/store.py backend/app/main.py backend/tests/test_people_api.py frontend/src/lib/api.js
git commit -m "feat(people): source-aware CRUD + paginated list + consent endpoints + containment-checked photo endpoint + api.js (M10 s1)"
```

---

## Task 8 — macOS Contacts connector card (`auth_kind="local"` + state-driven status)

The fifth Connectors card. `auth_kind="local"` describes the source and
authorization mechanism (a local, FDA-gated read), **not data residency**. Its
`access` is a deterministic Full-Disk-Access probe (`granted`/`denied`/
`unknown`); its `status` is driven by the persisted consent state; and
`configured=False` off macOS renders as an "unsupported" state. Reuses the
connector recipe from the current plan's Tasks 5–7.

**Files:**
- Modify: `backend/app/schemas.py` (widen `ConnectorInfo` Literals + `access`)
- Modify: `backend/app/routers/connectors.py` (catalog + probe + `_contacts_connector`)
- Modify: `backend/tests/test_connectors.py` (append `local` to the order-lock assertion)
- Create: `backend/tests/test_connectors_contacts.py`
- (No frontend here — the `local` card renders via **Task 9's** `ContactsLocalCard`.)

**Interfaces:**
- Consumes: `macos_contacts.is_supported() -> bool` (Task 4 — drives `configured`, replacing raw `sys.platform`); `macos_contacts.probe_access(root=DEFAULT_ROOT) -> str` (Task 4); `store.get_contacts_state() -> dict` (Task 6).
- Produces: a 5th `ConnectorInfo` `name="macos_contacts"`, `auth_kind="local"`, `access ∈ {granted,denied,unknown}`, status from consent state.

- [ ] **Step 1: Widen the schema** — `backend/app/schemas.py` (brief)

```python
    name: Literal["google", "whoop", "moodle", "plaid", "macos_contacts"]
    ...
    auth_kind: Literal["oauth", "token", "link", "local"]
    ...
    access: Literal["granted", "denied", "unknown"] = "unknown"   # macos_contacts only
```
(Keep `access` defaulted so the other four constructions stay valid.)

- [ ] **Step 2: Write the failing test** — `backend/tests/test_connectors_contacts.py` (brief)

```python
from fastapi.testclient import TestClient

from app.main import app
from app.routers import connectors
from app.store import store


def _card(client):
    return next(c for c in client.get("/api/connectors").json()
               if c["name"] == "macos_contacts")


def _state(**over):
    base = {"enabled": False, "status": "disabled", "access": "unknown",
            "normalization_region": None, "enabled_at": None,
            "last_sync_at": None, "last_error": None}
    base.update(over)
    return base


def test_contacts_card_connected(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: True)
    monkeypatch.setattr(connectors, "_contacts_access", lambda: "granted")
    monkeypatch.setattr(store, "get_contacts_state",
                        lambda: _state(enabled=True, status="ready", access="granted"))
    card = _card(TestClient(app))
    assert card["auth_kind"] == "local"
    assert card["access"] == "granted"
    assert card["status"] == "connected"


def test_contacts_card_denied(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: True)
    monkeypatch.setattr(connectors, "_contacts_access", lambda: "denied")
    monkeypatch.setattr(store, "get_contacts_state", lambda: _state(enabled=True))
    card = _card(TestClient(app))
    assert card["access"] == "denied"
    assert card["status"] == "not_connected"


def test_contacts_card_unsupported_off_darwin(monkeypatch):
    monkeypatch.setattr(connectors, "_contacts_configured", lambda: False)
    card = _card(TestClient(app))
    assert card["configured"] is False
    assert card["access"] == "unknown"
    assert card["status"] == "not_connected"
```

- [ ] **Step 3: Run to verify it fails** (brief)

Run: `cd backend && .venv/bin/python -m pytest tests/test_connectors_contacts.py -q`
Expected: FAIL — no `macos_contacts` card / no `_contacts_connector`.

- [ ] **Step 4: Implement** — `backend/app/routers/connectors.py`

Append to `_CATALOG`:
```python
    ("macos_contacts", "Apple Contacts", "local"),
```
In `_configured`, before the final `return False`:
```python
    if name == "macos_contacts":
        return _contacts_configured()
```
Add the helpers near `_plaid_connector`. Platform support and the FDA probe are
isolated behind `_contacts_configured` / `_contacts_access` — `_contacts_configured`
delegates to the seam's `macos_contacts.is_supported()` (never raw `sys.platform`),
so the autouse `configure(platform="linux")` and a per-test
`configure(fake_snapshot=…)`/`configure(platform="darwin")` drive the card
deterministically; off a supported host the card never probes and never reads state:
```python
def _contacts_configured() -> bool:
    # Platform support comes from the macos_contacts seam, NOT raw sys.platform,
    # so configure(platform=…)/configure(fake_snapshot=…) drive the card's
    # configured/access/status deterministically on macOS dev + CI alike
    # (contract: Testing/CI seam). is_supported() honors an injected platform.
    from ..providers import macos_contacts

    return macos_contacts.is_supported()


def _contacts_access() -> str:
    from ..config import settings
    from ..providers import macos_contacts

    return macos_contacts.probe_access(
        getattr(settings, "addressbook_root", macos_contacts.DEFAULT_ROOT)
    )


def _contacts_connector() -> ConnectorInfo:
    from ..store import store

    configured = _contacts_configured()
    access = _contacts_access() if configured else "unknown"
    state = store.get_contacts_state() if configured else {"enabled": False, "enabled_at": None}
    status = "connected" if (configured and state.get("enabled") and access == "granted") \
        else "not_connected"
    return ConnectorInfo(
        name="macos_contacts", label="Apple Contacts", auth_kind="local",
        configured=configured, status=status,
        connected_at=state.get("enabled_at"), provider_user_id=None,
        can_write_email=None, access=access, items=[],
    )
```
In `list_connectors`, add the short-circuit alongside plaid's:
```python
        if name == "macos_contacts":
            out.append(_contacts_connector())
            continue
```

- [ ] **Step 5: Update the order-lock test** — `backend/tests/test_connectors.py`

Append `local` to the `auth_kind` order assertion and bump any connector-count
assertion 4 → 5. `auth_kind` is host-independent (the card is always emitted;
only its `access`/`status` vary), so this needs no probe stubbing:
```python
    assert [c["auth_kind"] for c in body] == ["oauth", "oauth", "token", "link", "local"]
```

> **Frontend is Task 9, not here.** The Connectors UI `local` branch — the FDA
> access states, the pre-enable storage-disclosure gate, and the Sync /
> Disconnect / Forget controls — is implemented in **Task 9** as the
> `ContactsLocalCard` component (which owns the single `c.auth_kind === 'local'`
> render and the vault-gate exemption). This task ships **backend only**: the
> catalog entry, the `_contacts_configured` / `_contacts_access` probes, and the
> `_contacts_connector` card. Do NOT add an inline `local` branch to
> `ConnectorsPanel.jsx` here — it would duplicate `ContactsLocalCard`.

- [ ] **Step 6: Run tests + full suite + commit** (brief)

Run: `cd backend && .venv/bin/python -m pytest tests/test_connectors_contacts.py tests/test_connectors.py -q` then `.venv/bin/python -m pytest -q` (report the count)
```bash
git add backend/app/schemas.py backend/app/routers/connectors.py backend/tests/test_connectors_contacts.py backend/tests/test_connectors.py
git commit -m "feat(people): macOS Contacts connector card (auth_kind=local, FDA probe, state-driven status) — backend only (M10 s1)"
```

---

## Task 9 — Frontend (People CRM + status model + a11y + automated tests)

The People screen becomes a **usable CRM**, not a directory dump: it renders real rows from `api.listPeople()` (a union of manually-created people and the one-way macOS Contacts import), lets you **create a person by hand**, and opens a **source-aware detail/editor** — imported identity is READ-ONLY with a "from macOS Contacts" note, while the CRM-native fields (`relationship`, `notes`, `pinned`) are editable on every person. A **status model** makes the distinct sync states legible (first-sync, syncing, access-denied, stale, last-error, genuinely-empty, no-search-matches). In Settings › Connectors the `macos_contacts` card gets a `local` branch that is **exempt from every credential gate**, renders the FDA access state (granted/denied/unknown/unsupported) distinctly, shows the **PostgreSQL storage disclosure before enabling** (enable is gated on acknowledgement), and exposes Grant-FDA / Sync now / Disconnect / confirmed Forget-imported-data. This slice also stands up the frontend's first automated test runner — **Vitest + @testing-library/react** — with a CRMScreen test and a ConnectorsPanel local-card test.

The forbidden non-functional **"Draft a note"** button on each row is removed (it never worked); its space is reclaimed by the source-aware detail panel.

**Files:**
- Modify: `frontend/package.json` (dev deps + `test` scripts)
- Modify: `frontend/vite.config.js` (Vitest `test` block)
- Create: `frontend/src/test/setup.js` (jsdom + jest-dom + cleanup)
- Create: `frontend/src/screens/__tests__/CRMScreen.test.jsx`
- Create: `frontend/src/screens/__tests__/ConnectorsPanel.test.jsx`
- Modify: `frontend/src/components/ui.jsx` (`Avatar` gains an image-error fallback to initials)
- Reuse (no change): `frontend/src/lib/api.js` — the People/CRM reads/writes + contacts-consent lifecycle + `personPhotoUrl` all landed in Task 7 §7; this task consumes that single copy (see Step 5).
- Modify: `frontend/src/screens/CRMScreen.jsx` (full rewrite → real data + status model + search + manual create + source-aware editor + a11y)
- Modify: `frontend/src/screens/ConnectorsPanel.jsx` (`local` branch, gate exemption, **awaited** `refresh()`, `ContactsLocalCard`)
- Modify: `frontend/src/App.jsx` (pass `onOpenConnectors` to `CRMScreen`)

**Interfaces:**
- Consumes (backend contract types by name — do NOT redefine):
  - `api.listPeople() -> Promise<PersonOut[]>` where each row carries `phones: PhoneEntry[]`, `emails: EmailEntry[]` (contract "Typed handle schemas"), `source ∈ {'macos_contacts','manual'}`, `has_photo`, and the CRM-native fields (`relationship`, `relationship_strength`, `notes`, `pinned`, `last_contacted_at`).
  - `api.getConnectors() -> Promise<ConnectorInfo[]>`; the `macos_contacts` card projects `contacts_sync_state` for the UI as `{ name:'macos_contacts', label, auth_kind:'local', configured, access:'granted'|'denied'|'unknown', enabled, sync_status:'disabled'|'ready'|'syncing'|'stale'|'error'|'access_denied'|'unsupported', last_sync_at, last_error, count }`. `access` is exactly the `probe_access` return (granted/denied/unknown); the frontend derives a fourth **`unsupported`** display capability from `configured===false` or `sync_status==='unsupported'` (an `UNSUPPORTED_SCHEMA` snapshot per `SnapshotStatus`) so it is never mislabelled "denied".
  - Consent lifecycle endpoints (contract "Consent & lifecycle"): `POST /api/people/contacts/enable` (gated frontend-side on the storage-disclosure ack), `POST /api/people/contacts/disconnect`, `POST /api/people/contacts/forget`, plus `POST /api/people/sync` (one `apply_contacts_snapshot` pass, returns a `SyncResult`).
- Produces (frontend):
  - `api.personPhotoUrl(id)` (photo served as a file, so the URL is built against the configured API base — `127.0.0.1:<port>` in the packaged app — never a relative path), `api.enableContacts()`, `api.disconnectContacts()`, `api.forgetContacts()`, `api.syncContacts()`, and the `listPeople/getPerson/createPerson/updatePerson/deletePerson` read/write set (keep a single copy if the People-router task already added the CRUD subset).
  - `Avatar` with an `onError` fallback to initials; a rewritten `CRMScreen`; a `ContactsLocalCard` branch in `ConnectorsPanel`.

---

- [ ] **Step 1: Stand up the Vitest toolchain**

Add the dev dependencies and test scripts. From `frontend/`:
```bash
cd frontend && npm install -D vitest@^2.1.8 jsdom@^25.0.1 \
  @testing-library/react@^16.1.0 @testing-library/dom@^10.4.0 @testing-library/jest-dom@^6.6.3
```

Then set the two scripts in `frontend/package.json` (the `install -D` above already wrote the `devDependencies`; only the `scripts` block needs editing):
```json
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
```

Add the Vitest `test` block to `frontend/vite.config.js` (jsdom env, global `expect`, a setup file, and CSS disabled so `kit.css` imports don't need a real bundler):
```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Scuffed OS frontend. In dev, /api is proxied to the FastAPI backend on :8000
// so the app can call same-origin endpoints (no CORS dance during development).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  // Vitest (frontend unit/component tests). jsdom + Testing Library; the setup
  // file registers jest-dom matchers and auto-cleans the DOM between tests.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
    include: ['src/**/*.test.{js,jsx}'],
  },
})
```

Create the setup file — `frontend/src/test/setup.js`:
```js
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Unmount React trees + reset jsdom between tests so state can't leak.
afterEach(() => {
  cleanup()
})
```

Verify the runner boots (no tests yet, so vitest exits cleanly reporting "No test files found" — that is the expected pre-TDD state):
```bash
cd frontend && npm test
```
Expected: vitest runs and reports **no test files found** (exit non-fatal). If it errors on config, fix before continuing.

---

- [ ] **Step 2: Write the failing CRMScreen test** — `frontend/src/screens/__tests__/CRMScreen.test.jsx`

```jsx
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CRMScreen } from '../CRMScreen.jsx'
import { api } from '../../lib/api.js'

vi.mock('../../lib/api.js', () => ({
  api: {
    listPeople: vi.fn(),
    getConnectors: vi.fn(),
    personPhotoUrl: (id) => `/api/people/${id}/photo`,
    syncContacts: vi.fn(),
    createPerson: vi.fn(),
    updatePerson: vi.fn(),
    deletePerson: vi.fn(),
  },
}))

const importedPerson = {
  id: 7, source: 'macos_contacts', source_id: 'UID-7', display_name: 'Jane Doe',
  first_name: 'Jane', last_name: 'Doe', nickname: '', organization: 'Acme', job_title: '',
  phones: [{ value: '+15551234567', label: 'Mobile', normalized: '+15551234567' }],
  emails: [{ value: 'jane@icloud.com', label: 'Home', normalized: 'jane@icloud.com' }],
  has_photo: false, relationship: null, relationship_strength: null, notes: null,
  pinned: false, last_contacted_at: null, removed_from_source_at: null,
  created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getConnectors.mockResolvedValue([])   // no contacts card by default
})

describe('CRMScreen', () => {
  it('shows a loading state, then the empty onboarding when there are no people', async () => {
    let resolve
    api.listPeople.mockReturnValue(new Promise((r) => { resolve = r }))
    render(<CRMScreen />)
    expect(screen.getByText(/loading your people/i)).toBeInTheDocument()

    resolve([])
    expect(await screen.findByText(/no people yet/i)).toBeInTheDocument()
    // the empty CTA offers a manual add (distinct label from the header's "New person")
    expect(screen.getByRole('button', { name: /add a person/i })).toBeInTheDocument()
  })

  it('renders imported identity read-only with a macOS Contacts note; CRM fields stay editable', async () => {
    api.listPeople.mockResolvedValue([importedPerson])
    render(<CRMScreen />)

    const row = await screen.findByRole('button', { name: /jane doe/i })
    fireEvent.click(row)

    // read-only identity: the "from macOS Contacts" note + the email shown as text (no input)
    expect(await screen.findByText(/synced from macos contacts/i)).toBeInTheDocument()
    expect(screen.getByText('jane@icloud.com')).toBeInTheDocument()
    expect(screen.queryByLabelText('Email')).toBeNull()      // imported email is NOT an editable field
    expect(screen.queryByLabelText('Name')).toBeNull()       // imported identity name is read-only

    // CRM-native field IS editable
    expect(screen.getByLabelText(/relationship/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/screens/__tests__/CRMScreen.test.jsx`
Expected: FAIL — the current `CRMScreen` renders hardcoded sample people (e.g. "Priya Anand") and never shows "Loading your people…"; the loading assertion fails.

---

- [ ] **Step 4: Give `Avatar` an image-error fallback** — `frontend/src/components/ui.jsx`

`Avatar` already accepts `src` (renders `<img>`), but a broken/expired photo URL would leave an empty box. Add an `onError` fallback to initials, resetting on `src` change. Add a React import at the top of the file (the module currently imports nothing) and replace the `Avatar` export:

```jsx
/* Scuffed OS — UI primitives (the design-system components, 1:1).
   Pure, presentational, styled entirely via the .sa-* classes in kit.css and the
   token custom properties. No CSS-in-JS, no extra deps. */
import React from 'react'
```

```jsx
export function Avatar({ name = '', src, size = 'md', tint = 'green', ...rest }) {
  // A photo URL that 404s / expires must fall back to initials, never a blank box.
  const [failed, setFailed] = React.useState(false)
  React.useEffect(() => { setFailed(false) }, [src])
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
  const [bg, fg] = AV_TINTS[tint] || AV_TINTS.green
  const showImg = src && !failed
  return (
    <span className={`sa-avatar sa-avatar--${size}`} style={showImg ? undefined : { background: bg, color: fg }} {...rest}>
      {showImg ? <img src={src} alt={name} onError={() => setFailed(true)} /> : (initials || '?')}
    </span>
  )
}
```

> Note: `Avatar` now takes **`src` + an image-error fallback to initials**. Every People-screen avatar passes `src={p.has_photo ? api.personPhotoUrl(p.id) : undefined}` — when the photo is absent OR the image fails to load, the tinted initials render.

- [ ] **Step 5: Reuse the People/CRM api.js methods (added in Task 7) — do NOT redefine**

The full People/CRM client already landed in **Task 7 §7** (`frontend/src/lib/api.js`)
with the **correct request bodies**, and this task must keep exactly ONE copy of
each method:

- `enableContacts(ack = true)` POSTs `{ ack_storage_disclosure: true }` — the
  backend `POST /contacts/enable` **400s without the ack**. Do NOT add a second,
  no-body `enableContacts` override; it would silently 400.
- `forgetContacts()` POSTs `{ confirm: true }` — the backend `forget` 400s without it.
- `listPeople(params = {})`, `getPerson`, `createPerson`, `updatePerson`,
  `deletePerson`, `syncContacts`, `disconnectContacts`, and `personPhotoUrl`
  (built against the configured API `BASE`) are also from Task 7.

This task's `CRMScreen`/`ContactsLocalCard` consume that single copy verbatim
(`api.listPeople()` works — Task 7's `listPeople(params = {})` accepts a no-arg
call). If, and only if, a method is missing, add it there — never a duplicate.

- [ ] **Step 6: Rewrite `CRMScreen.jsx`** — real data, status model, controlled search, manual create, source-aware detail/editor, a11y

```jsx
/* Scuffed OS — Personal CRM (M10 s1): a usable People/CRM backed by real rows.
   Rows come from api.listPeople() — a union of manually-created people and the
   one-way macOS Contacts import (source='macos_contacts'). Imported IDENTITY is
   READ-ONLY here (edit it in the Contacts app); the CRM-native fields
   (relationship, notes, pinned) are editable on every person. The header status
   model makes the distinct sync states legible; the list never blocks on a sync. */
import React from 'react'
import { Card, Avatar, Badge, Button, IconButton, Checkbox } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const TINTS = ['sky', 'plum', 'green', 'honey', 'clay']
const tintFor = (p) => TINTS[(p.id || 0) % TINTS.length]
const isImported = (p) => p.source === 'macos_contacts'

const SR_ONLY = {
  position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
  overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0,
}
const INPUT_STYLE = {
  padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
  border: '1px solid var(--border-soft)', fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)', color: 'var(--text-strong)', width: '100%',
}
const TONE_TINT = {
  sky: { background: 'var(--sky-100)', color: 'var(--sky-600)' },
  honey: { background: 'var(--honey-100)', color: 'var(--honey-600)' },
  clay: { background: 'var(--clay-100)', color: 'var(--clay-600)' },
  muted: { background: 'var(--paper-200)', color: 'var(--text-muted)' },
}

// probe_access (Design Contract) returns only granted|denied|unknown; 'unsupported'
// is a frontend projection for a non-macOS host or an UNSUPPORTED_SCHEMA snapshot,
// kept distinct so we never mislabel it "denied".
function contactsCapability(c) {
  if (!c) return 'unknown'
  if (c.configured === false || c.sync_status === 'unsupported') return 'unsupported'
  return c.access || 'unknown'
}

// The sync-state banner descriptor (null when the import is off or idle-ready).
// Covers the distinct states: first-sync, syncing, access-denied, stale,
// last-error, and unsupported. (genuinely-empty / no-search-matches are handled
// in the list region below.)
function syncBanner(c) {
  if (!c || !c.enabled) return null
  const cap = contactsCapability(c)
  if (cap === 'unsupported') {
    return { tone: 'muted', icon: 'unplug', busy: false, title: 'Contacts import isn’t available on this device.' }
  }
  if (cap === 'denied' || c.sync_status === 'access_denied') {
    return {
      tone: 'clay', icon: 'alert-triangle', busy: false, denied: true,
      title: 'Full Disk Access is off — contacts can’t refresh.',
      detail: c.last_sync_at ? `Showing the last import from ${new Date(c.last_sync_at).toLocaleString()}.` : null,
    }
  }
  if (c.sync_status === 'syncing') {
    return {
      tone: 'sky', icon: 'refresh-cw', busy: true,
      title: c.last_sync_at ? 'Refreshing contacts…' : 'Importing your contacts for the first time…',
    }
  }
  if (c.sync_status === 'stale') {
    return {
      tone: 'honey', icon: 'clock', busy: false, retry: true, title: 'Contacts may be out of date.',
      detail: c.last_sync_at ? `Last synced ${new Date(c.last_sync_at).toLocaleString()}.` : null,
    }
  }
  if (c.sync_status === 'error') {
    return {
      tone: 'clay', icon: 'alert-triangle', busy: false, retry: true,
      title: 'The last contacts sync didn’t finish.', detail: c.last_error || null,
    }
  }
  return null
}

function matches(p, q) {
  if (!q.trim()) return true
  const hay = [p.display_name, p.organization, p.job_title,
    ...(p.emails || []).map((e) => e.value),
    ...(p.phones || []).map((ph) => ph.value)].filter(Boolean).join(' ').toLowerCase()
  return hay.includes(q.trim().toLowerCase())
}

function Field({ label, required, children }) {
  return (
    <label className="kit-field">
      <span className="kit-field__label">{label}{required ? ' *' : ''}</span>
      {children}
    </label>
  )
}

function ReadOnlyRow({ label, value }) {
  return (
    <div className="kit-field">
      <span className="kit-field__label">{label}</span>
      <span className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{value || '—'}</span>
    </div>
  )
}

function EmptyPeople({ contacts, onAdd, onOpenConnectors }) {
  const enabled = !!contacts?.enabled
  return (
    <div className="kit-stack" style={{ alignItems: 'center', padding: 32, textAlign: 'center', gap: 10 }}>
      <Icon name="users" />
      <p className="kit-row__title">{enabled ? 'No contacts to show yet' : 'No people yet'}</p>
      <p className="kit-muted" style={{ fontSize: 'var(--text-sm)', maxWidth: 320 }}>
        {enabled
          ? 'Your macOS Contacts import is on but hasn’t returned anyone yet.'
          : 'Add someone by hand, or import your macOS Contacts from Settings › Connectors.'}
      </p>
      <div className="kit-inline" style={{ gap: 8 }}>
        <Button variant="primary" size="sm" iconLeft={<Icon name="plus" />} onClick={onAdd}>Add a person</Button>
        {!enabled && onOpenConnectors && (
          <Button variant="secondary" size="sm" iconLeft={<Icon name="settings" />} onClick={onOpenConnectors}>
            Import from Contacts
          </Button>
        )}
      </div>
    </div>
  )
}

function PersonEditor({ onCancel, onSaved }) {
  const [name, setName] = React.useState('')
  const [email, setEmail] = React.useState('')
  const [phone, setPhone] = React.useState('')
  const [relationship, setRelationship] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [err, setErr] = React.useState('')

  const submit = async (e) => {
    e.preventDefault()
    if (!name.trim()) { setErr('A name is required.'); return }
    setBusy(true); setErr('')
    try {
      const created = await api.createPerson({
        display_name: name.trim(),
        emails: email.trim() ? [{ value: email.trim(), label: 'Home' }] : [],
        phones: phone.trim() ? [{ value: phone.trim(), label: 'Mobile' }] : [],
        relationship: relationship.trim() || null,
        notes: notes.trim() || null,
      })
      await onSaved(created)
    } catch (e2) {
      setErr(e2?.message || 'Couldn’t save this person.'); setBusy(false)
    }
  }

  return (
    <Card title="New person" variant="sunken">
      <form className="kit-stack" style={{ gap: 10 }} onSubmit={submit}>
        <Field label="Name" required>
          <input aria-label="Name" autoFocus value={name} style={INPUT_STYLE} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Email">
          <input aria-label="Email" type="email" value={email} style={INPUT_STYLE} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Phone">
          <input aria-label="Phone" value={phone} style={INPUT_STYLE} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label="Relationship">
          <input aria-label="Relationship" value={relationship} style={INPUT_STYLE} onChange={(e) => setRelationship(e.target.value)} />
        </Field>
        <Field label="Notes">
          <textarea aria-label="Notes" rows={3} value={notes} style={{ ...INPUT_STYLE, resize: 'vertical' }} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        {err && <p role="alert" style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--clay-600)' }}>{err}</p>}
        <div className="kit-inline" style={{ gap: 8 }}>
          <Button type="submit" variant="primary" size="sm" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  )
}

function PersonDetail({ person, onChanged, onDeleted }) {
  const imported = isImported(person)
  const [displayName, setDisplayName] = React.useState(person.display_name || '')
  const [relationship, setRelationship] = React.useState(person.relationship || '')
  const [notes, setNotes] = React.useState(person.notes || '')
  const [pinned, setPinned] = React.useState(!!person.pinned)
  const [busy, setBusy] = React.useState(false)
  const [msg, setMsg] = React.useState('')
  const [confirmDelete, setConfirmDelete] = React.useState(false)

  // Re-seed the form whenever a different person is selected.
  React.useEffect(() => {
    setDisplayName(person.display_name || ''); setRelationship(person.relationship || '')
    setNotes(person.notes || ''); setPinned(!!person.pinned); setMsg(''); setConfirmDelete(false)
  }, [person.id])

  const save = async () => {
    setBusy(true); setMsg('')
    // sync never writes CRM-native fields; conversely, imported identity is edited
    // in the Contacts app, so we only send display_name for manual people.
    const patch = { relationship: relationship.trim() || null, notes: notes.trim() || null, pinned }
    if (!imported) patch.display_name = displayName.trim() || person.display_name
    try { await api.updatePerson(person.id, patch); await onChanged(); setMsg('Saved.') }
    catch (e) { setMsg(e?.message || 'Couldn’t save.') }
    finally { setBusy(false) }
  }

  return (
    <Card title={person.display_name || 'Unnamed'} variant="sunken"
      eyebrow={imported ? 'From macOS Contacts' : 'Manual contact'}
      action={<Avatar name={person.display_name} tint={tintFor(person)}
        src={person.has_photo ? api.personPhotoUrl(person.id) : undefined} />}>
      <div className="kit-stack" style={{ gap: 14 }}>
        <section aria-label="Identity" className="kit-stack" style={{ gap: 10 }}>
          {imported ? (
            <>
              <p className="kit-muted" style={{ margin: 0, fontSize: 'var(--text-sm)', display: 'flex', gap: 6, alignItems: 'center' }}>
                <Icon name="apple" /> Synced from macOS Contacts — edit these in the Contacts app.
              </p>
              <ReadOnlyRow label="Name" value={person.display_name} />
              {person.organization && <ReadOnlyRow label="Organization" value={person.organization} />}
              {person.job_title && <ReadOnlyRow label="Title" value={person.job_title} />}
              {(person.emails || []).map((e, i) => <ReadOnlyRow key={`e${i}`} label={e.label || 'Email'} value={e.value} />)}
              {(person.phones || []).map((ph, i) => <ReadOnlyRow key={`p${i}`} label={ph.label || 'Phone'} value={ph.value} />)}
            </>
          ) : (
            <Field label="Name">
              <input aria-label="Name" value={displayName} style={INPUT_STYLE} onChange={(e) => setDisplayName(e.target.value)} />
            </Field>
          )}
        </section>

        <section aria-label="CRM details" className="kit-stack" style={{ gap: 10 }}>
          <Field label="Relationship">
            <input aria-label="Relationship" value={relationship} style={INPUT_STYLE} onChange={(e) => setRelationship(e.target.value)} />
          </Field>
          <Field label="Notes">
            <textarea aria-label="Notes" rows={3} value={notes} style={{ ...INPUT_STYLE, resize: 'vertical' }} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <Checkbox checked={pinned} onChange={(e) => setPinned(e.target.checked)} label="Pinned" />
        </section>

        <div aria-live="polite" style={SR_ONLY}>{msg}</div>
        {msg && <p role="status" className="kit-muted" style={{ margin: 0, fontSize: 'var(--text-sm)' }}>{msg}</p>}

        <div className="kit-inline" style={{ gap: 8 }}>
          <Button variant="primary" size="sm" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</Button>
          {!imported && (confirmDelete ? (
            <>
              <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>Delete this person?</span>
              <Button variant="secondary" size="sm" disabled={busy}
                onClick={async () => { setBusy(true); try { await api.deletePerson(person.id); await onDeleted() } catch (e) { setMsg(e?.message || 'Delete failed.'); setBusy(false) } }}>Delete</Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            </>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>Delete</Button>
          ))}
        </div>
      </div>
    </Card>
  )
}

export function CRMScreen({ onOpenConnectors }) {
  const [people, setPeople] = React.useState(null)
  const [contacts, setContacts] = React.useState(null)   // the macos_contacts connector card, or null
  const [error, setError] = React.useState('')
  const [q, setQ] = React.useState('')
  const [selectedId, setSelectedId] = React.useState(null)
  const [creating, setCreating] = React.useState(false)
  const [syncing, setSyncing] = React.useState(false)
  const [notice, setNotice] = React.useState('')

  const refresh = React.useCallback(async () => {
    try {
      const [ppl, cards] = await Promise.all([
        api.listPeople(),
        api.getConnectors().catch(() => []),
      ])
      setPeople(ppl)
      setContacts((cards || []).find((k) => k.name === 'macos_contacts') || null)
      setError('')
      return ppl
    } catch (e) {
      setError(e?.message || 'Couldn’t load your people.')
      throw e
    }
  }, [])

  React.useEffect(() => { refresh().catch(() => {}) }, [refresh])

  // Refetch when the user returns to the app/tab: a background startup sync or a
  // manual sync from Connectors may have changed the data while we were away.
  React.useEffect(() => {
    const onFocus = () => refresh().catch(() => {})
    const onVisible = () => { if (document.visibilityState === 'visible') refresh().catch(() => {}) }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  // While a sync is in flight, poll until it settles so the list + banner update
  // the moment the (startup or manual) import completes. Self-clearing.
  const syncStatus = contacts?.sync_status
  React.useEffect(() => {
    if (syncStatus !== 'syncing') return undefined
    const id = setInterval(() => { refresh().catch(() => {}) }, 2500)
    return () => clearInterval(id)
  }, [syncStatus, refresh])

  const runSync = React.useCallback(async () => {
    setSyncing(true); setNotice('Syncing contacts…')
    try {
      await api.syncContacts()
      await refresh()
      setNotice('Contacts synced.')
    } catch (e) {
      setNotice(e?.message || 'Sync failed.')
    } finally {
      setSyncing(false)
    }
  }, [refresh])

  // ---- loading / hard-error gates ----
  if (people === null && !error) {
    return <Card variant="flat" aria-busy="true"><p className="kit-muted">Loading your people…</p></Card>
  }
  if (people === null && error) {
    return (
      <Card variant="flat" role="alert">
        <p className="kit-row__title">{error}</p>
        <div className="kit-inline" style={{ marginTop: 10 }}>
          <Button variant="primary" size="sm" iconLeft={<Icon name="refresh-cw" />}
            onClick={() => refresh().catch(() => {})}>Retry</Button>
        </div>
      </Card>
    )
  }

  const banner = syncBanner(contacts)
  const filtered = (people || []).filter((p) => matches(p, q))
  const selected = (people || []).find((p) => p.id === selectedId) || null
  const emptyAll = (people || []).length === 0
  const noMatches = !emptyAll && filtered.length === 0

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1.5fr 1fr' }}>
      <Card
        title="People"
        eyebrow={`${(people || []).length} ${(people || []).length === 1 ? 'contact' : 'contacts'}`}
        action={
          <div className="kit-inline" style={{ gap: 8 }}>
            <div className="kit-search" style={{ width: 180 }}>
              <Icon name="search" />
              <input aria-label="Search people" placeholder="Search people"
                value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <IconButton label="New person" onClick={() => { setCreating(true); setSelectedId(null) }}>
              <Icon name="plus" />
            </IconButton>
          </div>
        }
      >
        {/* Screen-reader status region for sync announcements. */}
        <div aria-live="polite" style={SR_ONLY}>{notice}</div>

        {banner && (
          <Card variant="flat" role="status" aria-busy={banner.busy ? 'true' : 'false'}
            style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, background: 'var(--surface-sunken)' }}>
            <span className="kit-statline__ico" style={TONE_TINT[banner.tone]}><Icon name={banner.icon} /></span>
            <div style={{ flex: 1 }}>
              <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{banner.title}</p>
              {banner.detail && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{banner.detail}</p>}
            </div>
            {banner.denied && onOpenConnectors && (
              <Button variant="secondary" size="sm" onClick={onOpenConnectors}>Fix access</Button>
            )}
            {banner.retry && (
              <Button variant="secondary" size="sm" disabled={syncing}
                iconLeft={<Icon name="refresh-cw" />} onClick={runSync}>Sync now</Button>
            )}
          </Card>
        )}

        {emptyAll ? (
          <EmptyPeople contacts={contacts} onAdd={() => { setCreating(true); setSelectedId(null) }} onOpenConnectors={onOpenConnectors} />
        ) : noMatches ? (
          <div className="kit-stack" style={{ alignItems: 'center', padding: 24, textAlign: 'center', gap: 8 }}>
            <Icon name="search" />
            <p className="kit-row__title">No matches for “{q}”</p>
            <Button variant="ghost" size="sm" onClick={() => setQ('')}>Clear search</Button>
          </div>
        ) : (
          <ul className="kit-stack" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {filtered.map((p) => (
              <li key={p.id}>
                <button type="button" className="kit-person" aria-pressed={p.id === selectedId}
                  style={{ width: '100%', background: 'none', border: 0, textAlign: 'left', cursor: 'pointer' }}
                  onClick={() => { setSelectedId(p.id); setCreating(false) }}>
                  <Avatar name={p.display_name} tint={tintFor(p)}
                    src={p.has_photo ? api.personPhotoUrl(p.id) : undefined} />
                  <div className="kit-person__main">
                    <p className="kit-person__name">
                      {p.display_name || 'Unnamed'}
                      {p.relationship && <Badge color="sky">{p.relationship}</Badge>}
                      {isImported(p) && <Badge color="neutral">Contacts</Badge>}
                    </p>
                    <p className="kit-person__sub">
                      {p.emails?.[0]?.value || p.phones?.[0]?.value || p.organization || '—'}
                    </p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="kit-col">
        {creating ? (
          <PersonEditor key="new" onCancel={() => setCreating(false)}
            onSaved={async (created) => { setCreating(false); await refresh(); setSelectedId(created.id) }} />
        ) : selected ? (
          <PersonDetail key={selected.id} person={selected} onChanged={refresh}
            onDeleted={async () => { setSelectedId(null); await refresh() }} />
        ) : (
          <Card title="Details" variant="sunken">
            <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
              Select a person to see their details, or add someone new.
            </p>
          </Card>
        )}
      </div>
    </div>
  )
}
```

Wire the prop through — `frontend/src/App.jsx` (the `screen === 'people'` line):
```jsx
  else if (screen === 'people') body = <CRMScreen onOpenConnectors={onOpenConnectors} />
```

- [ ] **Step 7: Run the CRMScreen test to verify it passes**

Run: `cd frontend && npx vitest run src/screens/__tests__/CRMScreen.test.jsx`
Expected: PASS (2)

---

- [ ] **Step 8: Write the failing ConnectorsPanel local-card test** — `frontend/src/screens/__tests__/ConnectorsPanel.test.jsx`

```jsx
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConnectorsPanel } from '../ConnectorsPanel.jsx'
import { api } from '../../lib/api.js'

vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => false }))
vi.mock('../../lib/api.js', () => ({
  api: {
    getConnectors: vi.fn(),
    settingsGetSecrets: vi.fn(),
    enableContacts: vi.fn(),
    disconnectContacts: vi.fn(),
    forgetContacts: vi.fn(),
    syncContacts: vi.fn(),
  },
}))

const localCard = (over = {}) => ({
  name: 'macos_contacts', label: 'Apple Contacts', auth_kind: 'local', configured: true,
  status: 'not_connected', access: 'denied', enabled: false, sync_status: 'disabled',
  last_sync_at: null, last_error: null, count: 0, items: [], connected_at: null,
  provider_user_id: null, can_write_email: null, ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.settingsGetSecrets.mockResolvedValue({ vault_ok: true })
})

describe('ConnectorsPanel — macOS Contacts (local)', () => {
  it('offers Grant Full Disk Access when denied, exempt from the vault gate', async () => {
    api.settingsGetSecrets.mockResolvedValue({ vault_ok: false })   // OAuth connects gated…
    api.getConnectors.mockResolvedValue([localCard({ access: 'denied' })])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)
    // …but the local card still exposes Grant FDA regardless of the vault state
    expect(await screen.findByRole('button', { name: /grant full disk access/i })).toBeInTheDocument()
  })

  it('gates Enable on acknowledging the PostgreSQL storage disclosure', async () => {
    api.getConnectors.mockResolvedValue([localCard()])
    api.enableContacts.mockResolvedValue({})
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    const enable = await screen.findByRole('button', { name: /enable contacts import/i })
    expect(enable).toBeDisabled()                                    // no acknowledgement yet
    expect(screen.getByText(/postgresql database/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: /acknowledge/i }))
    expect(enable).toBeEnabled()

    fireEvent.click(enable)
    await waitFor(() => expect(api.enableContacts).toHaveBeenCalledTimes(1))
  })
})
```

- [ ] **Step 9: Run to verify it fails**

Run: `cd frontend && npx vitest run src/screens/__tests__/ConnectorsPanel.test.jsx`
Expected: FAIL — the current `ConnectorsPanel` has no `local` branch, so the `macos_contacts` card renders no "Grant Full Disk Access" or "Enable Contacts import" controls; both queries fail.

---

- [ ] **Step 10: Add the `local` branch to `ConnectorsPanel.jsx`**

**(a)** Make `refresh` return the connectors promise so handlers can **await** it — replace the `refresh` callback (~lines 51–58):
```jsx
  const refresh = React.useCallback(() => {
    const loaded = api.getConnectors()
      .then((c) => { setConnectors(c); setError('') })
      .catch((e) => setError(e?.message || 'Failed to load connectors'))
    api.settingsGetSecrets()
      .then((s) => setVaultOk(s.vault_ok !== false))
      .catch(() => setVaultOk(true))
    return loaded            // the local-card actions await this to reflect new state
  }, [])
```

**(b)** Exempt `local` from the credential gate — replace `connectDisabled` (~line 160):
```jsx
  const connectDisabled = (c) => busy === c.name
    || (c.auth_kind !== 'token' && c.auth_kind !== 'local' && (!c.configured || !vaultOk))
```

**(c)** Render the branch inside the card body, after the Plaid `link` block (right before the destructive-confirm block ~line 292):
```jsx
            {/* Local connector: macOS Contacts (FDA-gated, PostgreSQL-backed) */}
            {c.auth_kind === 'local' && (
              <ContactsLocalCard c={c} refresh={refresh} setError={setError} />
            )}
```

**(d)** Add the module-scope helpers + `ContactsLocalCard` component (place near the top of the file, after `openExternal`):
```jsx
// Storage disclosure shown BEFORE the user can enable the Contacts import. It is
// deliberately explicit that structured contact fields land in the configured
// PostgreSQL database, which MAY be remote (contract "Persistence & Privacy").
const CONTACTS_DISCLOSURE = 'Your contacts’ names, phone numbers, email addresses, '
  + 'organization and photos are read locally and read-only from the macOS Contacts app. '
  + 'The structured fields are then saved to the PostgreSQL database this app is configured '
  + 'to use — which may run on this Mac or on a remote/self-hosted server; when it is remote, '
  + 'that contact data travels over the network to it. Photos stay on this Mac. Contacts are '
  + 'never sent to any AI provider or third-party service.'

// FDA System Settings deep link (macOS): Privacy & Security → Full Disk Access.
const FDA_DEEP_LINK = 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'

// probe_access returns granted|denied|unknown; 'unsupported' is a projection for a
// non-macOS host or an UNSUPPORTED_SCHEMA snapshot — rendered as its own state.
function contactsCapability(c) {
  if (!c) return 'unknown'
  if (c.configured === false || c.sync_status === 'unsupported') return 'unsupported'
  return c.access || 'unknown'
}

const ACCESS_TITLE = {
  granted: 'Full Disk Access granted — contacts are importing.',
  denied: 'Full Disk Access is off.',
  unknown: 'Checking Full Disk Access…',
  unsupported: 'Contacts import isn’t available on this device.',
}
const ACCESS_ICON = { granted: 'check-check', denied: 'alert-triangle', unknown: 'clock', unsupported: 'unplug' }
const ACCESS_TINT = {
  granted: { background: 'var(--green-100)', color: 'var(--green-600)' },
  denied: { background: 'var(--clay-100)', color: 'var(--clay-600)' },
  unknown: { background: 'var(--honey-100)', color: 'var(--honey-600)' },
  unsupported: { background: 'var(--paper-200)', color: 'var(--text-muted)' },
}

function contactsSyncLine(c) {
  if (c.sync_status === 'syncing') return 'Syncing…'
  if (c.sync_status === 'error' && c.last_error) return c.last_error
  if (c.last_sync_at) {
    return `Last synced ${new Date(c.last_sync_at).toLocaleString()}`
      + (c.count != null ? ` · ${c.count} contacts` : '')
  }
  return 'Not synced yet.'
}

function ContactsLocalCard({ c, refresh, setError }) {
  const [ack, setAck] = React.useState(false)
  const [busy, setBusy] = React.useState('')            // 'enable' | 'sync' | 'disconnect' | 'forget'
  const [confirmForget, setConfirmForget] = React.useState(false)
  const cap = contactsCapability(c)

  const openSettings = () => openExternal(FDA_DEEP_LINK)
    .catch((e) => setError(e?.message || 'Could not open System Settings'))

  const run = (which, call) => async () => {
    setBusy(which)
    try { await call(); await refresh() }
    catch (e) { setError(e?.message || 'Something went wrong') }
    finally { setBusy('') }
  }
  const enable = run('enable', () => api.enableContacts())
  const sync = run('sync', () => api.syncContacts())
  const disconnect = run('disconnect', () => api.disconnectContacts())
  const forget = async () => {
    setBusy('forget')
    try { await api.forgetContacts(); await refresh(); setConfirmForget(false) }
    catch (e) { setError(e?.message || 'Could not forget imported data') }
    finally { setBusy('') }
  }

  // Not available on this device (non-macOS host or unrecognized schema).
  if (cap === 'unsupported') {
    return <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{ACCESS_TITLE.unsupported}</p>
  }

  // Import OFF → storage disclosure + acknowledgement gate before enabling.
  if (!c.enabled) {
    return (
      <div className="kit-stack" style={{ gap: 10 }}>
        <Card variant="flat" style={{ background: 'var(--surface-sunken)' }}>
          <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>Before you turn this on</p>
          <p className="kit-muted" style={{ fontSize: 'var(--text-sm)', marginTop: 6 }}>{CONTACTS_DISCLOSURE}</p>
        </Card>
        <label className="kit-inline" style={{ gap: 8, alignItems: 'flex-start', cursor: 'pointer' }}>
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)}
            aria-label="Acknowledge that contacts are stored in the configured PostgreSQL database" />
          <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
            I understand where my contact data is stored.
          </span>
        </label>
        <div className="kit-inline" style={{ gap: 8 }}>
          <Button variant="primary" size="sm" disabled={!ack || busy === 'enable'} onClick={enable}>
            {busy === 'enable' ? 'Enabling…' : 'Enable Contacts import'}
          </Button>
          {c.access !== 'granted' && (
            <Button variant="secondary" size="sm" onClick={openSettings}>Grant Full Disk Access</Button>
          )}
        </div>
      </div>
    )
  }

  // Import ON → access state (granted/denied/unknown rendered distinctly) + controls.
  return (
    <div className="kit-stack" style={{ gap: 10 }} aria-busy={c.sync_status === 'syncing' ? 'true' : 'false'}>
      <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
        <span className="kit-statline__ico" style={ACCESS_TINT[cap]}><Icon name={ACCESS_ICON[cap]} /></span>
        <div style={{ flex: 1 }}>
          <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{ACCESS_TITLE[cap]}</p>
          <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{contactsSyncLine(c)}</p>
        </div>
      </div>

      {cap !== 'granted' && (
        <Button variant="secondary" size="sm" onClick={openSettings}>Grant Full Disk Access</Button>
      )}

      <div className="kit-inline" style={{ gap: 8 }}>
        <Button variant="primary" size="sm" disabled={busy === 'sync' || c.sync_status === 'syncing'}
          iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync now</Button>
        <Button variant="secondary" size="sm" disabled={busy === 'disconnect'} onClick={disconnect}>Disconnect</Button>
      </div>

      {confirmForget ? (
        <Card variant="flat" style={{ background: 'var(--clay-100)' }}>
          <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>
            Delete every imported contact and photo from ScuffedOS? People you’ve added notes or a
            relationship to are kept as manual contacts; the rest are removed. This can’t be undone.
          </p>
          <div className="kit-inline" style={{ gap: 8, marginTop: 8 }}>
            <Button variant="primary" size="sm" disabled={busy === 'forget'} onClick={forget}>
              {busy === 'forget' ? 'Forgetting…' : 'Forget imported data'}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setConfirmForget(false)}>Cancel</Button>
          </div>
        </Card>
      ) : (
        <Button variant="ghost" size="sm" onClick={() => setConfirmForget(true)}>Forget imported data…</Button>
      )}
    </div>
  )
}
```

> `ContactsLocalCard` uses `Card`, `Button`, `Icon`, `api`, and `openExternal` — all already imported/defined at the top of `ConnectorsPanel.jsx`. `StatusChip` in the card header still renders `c.status`; `not_connected` reads "Not connected" for the local card while the import is off, which matches the disclosure-gated state.

- [ ] **Step 11: Run the ConnectorsPanel test to verify it passes**

Run: `cd frontend && npx vitest run src/screens/__tests__/ConnectorsPanel.test.jsx`
Expected: PASS (2)

---

- [ ] **Step 12: Run the full frontend suite + a browser smoke + commit**

Run the whole frontend test suite (report the count):
```bash
cd frontend && npm test
```
Expected: PASS — **4 tests across 2 files**. (The backend `pytest` baseline of **703 collected** is untouched by this frontend-only task.)

Optional live smoke (run-scuffedos skill / `preview_start`): open Settings › Connectors → the "Apple Contacts" card shows the storage disclosure + an acknowledgement checkbox that ungates "Enable Contacts import"; a denied FDA state shows "Grant Full Disk Access". Open People → the empty onboarding (or, after enabling + syncing, real rows with photo→initials fallback); click a synced person → identity is read-only with the "from macOS Contacts" note while Relationship/Notes/Pinned stay editable. Check `read_console_messages` for errors.

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js \
  frontend/src/test/setup.js \
  frontend/src/screens/__tests__/CRMScreen.test.jsx frontend/src/screens/__tests__/ConnectorsPanel.test.jsx \
  frontend/src/components/ui.jsx frontend/src/lib/api.js \
  frontend/src/screens/CRMScreen.jsx frontend/src/screens/ConnectorsPanel.jsx frontend/src/App.jsx
git commit -m "feat(people): real People CRM (status model + source-aware editor + a11y) + Contacts local connector card w/ storage-disclosure gate; add Vitest/RTL + CRMScreen & ConnectorsPanel tests (M10 s1)"
```

---

### Notes for the implementer

- **Status model → 7 distinct states.** `syncBanner()` covers *first-sync* (`syncing` + `last_sync_at == null`), *syncing* (`syncing` + prior sync), *access-denied* (`denied` / `access_denied`), *stale*, and *last-error* (`error` + `last_error`); the list region covers *genuinely-empty* (`emptyAll`) and *no-search-matches* (`noMatches`, only when `q` is non-empty). `unsupported` is the sixth banner variant for non-macOS/`UNSUPPORTED_SCHEMA`.
- **Refetch triggers.** initial mount; `focus` + `visibilitychange` (startup-sync completion / returning from Connectors); a bounded 2.5s poll while `sync_status==='syncing'`; and after every mutation (`createPerson`/`updatePerson`/`deletePerson`/`syncContacts`) since each awaits `refresh()`.
- **Awaited refresh.** `ConnectorsPanel.refresh()` now returns the connectors promise; the local-card actions (`enable`/`sync`/`disconnect`/`forget`) all `await refresh()` so the card re-renders against fresh state deterministically (the test asserts on the post-enable call).
- **Photo URLs + fallback.** `api.personPhotoUrl(id)` builds `${BASE}/api/people/${id}/photo` against the configured API base (relative `/api` would break inside the packaged `.app`); `Avatar`'s `onError` always falls back to tinted initials.
- **a11y.** controlled `q` search input with `aria-label`; `aria-busy` on the loading card, sync banner, and the local card while syncing; `aria-live="polite"` regions announce sync/save notices; every editable control is a real `<label>`/`aria-label` pair; person rows and actions are native focusable `<button>`s with visible (un-suppressed) focus outlines; `role="alert"` on hard errors + `role="status"` on transient notices; explicit Retry / Sync-now / Fix-access controls.
- **Do NOT redefine** `ContactsSnapshot`/`SnapshotStatus`/`SyncResult`/`apply_contacts_snapshot`/`contacts_sync_state`/`PhoneEntry`/`EmailEntry`/`photo_key` — this task only consumes their JSON projection through `api.listPeople()` / `api.getConnectors()` and the consent-lifecycle endpoints.

---

## Task 10: Tests / CI hardening (shared fixtures, deployment-aware integration, migration + connector locks)

The unit tests in Tasks 1–9 prove each piece in isolation. This task makes the
whole suite deterministic on **both** CI backends the project already runs
(`pytest` against the pgvector Postgres service, then `TEST_DATABASE_URL= pytest`
against in-memory SQLite — see `.github/workflows/ci.yml`) and on a macOS dev
box, then adds the cross-cutting integration tests the contract calls out:
remote-PostgreSQL outage, transaction rollback, partial reads, partial-upsert
failure, overlapping ticks, and advisory-lock contention. It also proves a
**remote DSN is accepted** (never refused) and extends the canonical migration +
connector-order locks to the three new tables and the fifth card.

**Files:**
- Modify: `backend/tests/conftest.py` (global autouse Contacts seam + temp photo/App-Support roots; reuse — do NOT hand-roll `create_engine("sqlite://")`)
- Modify: `backend/tests/test_migrations.py` (extend `ALL_TABLES` + people-domain column/index/constraint assertions)
- Modify: `backend/tests/test_connectors.py` (five-card order + auth-kind lock, deterministic probe)
- Create: `backend/tests/test_contacts_ci.py` (remote DSN accepted, outage-is-error, rollback, partial read, partial upsert, overlapping-apply serialization)
- Create: `backend/tests/test_macos_contacts_acceptance.py` (manual signed-package checklist, skipped in CI)
- Modify: `backend/pytest.ini` (register the `manual` marker)

**Interfaces (Consumes):**
- `macos_contacts.configure(*, fake_snapshot: ContactsSnapshot | None = None, platform: str | None = None) -> None`, `macos_contacts.probe_access(root=DEFAULT_ROOT) -> str`, `macos_contacts.read_snapshot(...) -> ContactsSnapshot`, `ContactsSnapshot`/`SnapshotStatus` (Task 4).
- `store.apply_contacts_snapshot(snapshot, now) -> SyncResult`, `store.list_people(include_removed=False)`, `store.set_contacts_enabled(enabled: bool, *, region: str | None = None, now: datetime | None = None) -> dict` and `store.get_contacts_state() -> dict` (the consent get/set helpers from Task 3).
- `contacts_sync.tick(now=None) -> SyncResult`, `contacts_sync.configure(override="unset")` (Task 6).
- `NormalizedPerson` (Task 3), `db.make_engine`, `db.normalize_database_url` (existing).
- Shared fixtures already in `conftest.py`: `fresh_db` (binds `store` to `make_engine(TEST_DATABASE_URL)`), `client` (`TestClient(app)`), `no_external_services`, `attachments_tmpdir`.

---

- [ ] **Step 1: Add the failing guard test** — `backend/tests/test_contacts_ci.py`

This test asserts the *global* seam is active for every test in the suite: on a
macOS dev box the reader must NOT touch the real AddressBook, and the background
sync loop must never auto-start. It fails until the conftest seam lands.

```python
"""CI hardening for the People/CRM + Contacts slice (M10 s1).

Every test in the suite runs with real Contacts probing forced OFF (so the same
suite is deterministic on a macOS dev box and on the Ubuntu CI runner) via the
autouse seam in conftest.py. These tests exercise the deployment-aware paths the
contract calls out: a remote PostgreSQL outage is a FAILED sync (never 'empty'),
apply is atomic, partial reads never reconcile, a per-record failure degrades to
'partial' without soft-deleting absent rows, and overlapping applies serialize
under the process + advisory lock. All run against whatever TEST_DATABASE_URL is
configured (Postgres on CI, SQLite locally), so the threaded test doubles as the
pg_advisory_xact_lock contention test on the Postgres leg.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app import contacts_sync
from app.db import make_engine, normalize_database_url
from app.providers import macos_contacts
from app.providers.base import NormalizedPerson
from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus
from app.store import store

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def _person(source_id: str, name: str, phone: str) -> NormalizedPerson:
    return NormalizedPerson(
        source="macos_contacts", source_id=source_id, display_name=name,
        phones=[{"value": phone, "label": "Mobile"}], emails=[],
    )


def _snap(status: SnapshotStatus, people: list[NormalizedPerson]) -> ContactsSnapshot:
    return ContactsSnapshot(
        status=status, people=people,
        stores_total=1, stores_read=1, store_ids=["local"],
    )


def test_real_contacts_probing_disabled_by_default():
    # The autouse conftest seam forces a non-darwin platform, so a probe never
    # opens the real AddressBook regardless of the host OS.
    assert macos_contacts.probe_access() == "denied"
    # ...and the background sync loop is not armed under test.
    from app.config import settings
    assert settings.contacts_sync_enabled is False
```

- [ ] **Step 2: Run to verify it fails**

```
cd backend && .venv/bin/python -m pytest tests/test_contacts_ci.py::test_real_contacts_probing_disabled_by_default -q
```
Expected: FAIL — on a macOS dev box `probe_access()` returns `"granted"`/`"unknown"` (real seam absent) and `settings.contacts_sync_enabled` is `True`.

- [ ] **Step 3: Add the shared Contacts seam to `conftest.py`**

Two changes, reusing the file's existing autouse pattern (never a raw
`create_engine("sqlite://")` — `fresh_db` already binds `store` to
`make_engine(TEST_DATABASE_URL)`).

3a. Extend the top-of-file import that already pulls the sync modules:
```python
from app import (
    contacts_sync, email_draft, email_sync, email_triage, finance_sync,
    fitness_sync, food_db, llm, memory_engine, moodle_sync, providers, reminders,
)
from app.providers import macos_contacts
```

3b. Fold Contacts into the existing `no_external_services` autouse fixture so the
reader is forced offline and the loop disarmed for **every** test unless a test
opts in with `macos_contacts.configure(fake_snapshot=...)`:
```python
@pytest.fixture(autouse=True)
def no_external_services():
    """Tests never reach the Claude API, OpenAI, Mem0, USDA, osascript, WHOOP, or
    the real macOS AddressBook — install a fake explicitly (each module's
    configure seam) when needed."""
    llm.configure(None)
    memory_engine.configure(None)
    food_db.configure(None)
    reminders.configure(None)
    providers.configure([])
    fitness_sync.configure(None)
    email_triage.configure(None)
    email_sync.configure(None)
    email_draft.configure(None)
    moodle_sync.configure(None)
    finance_sync.configure(None)
    # Contacts: force the reader off real disk on every platform (macOS dev +
    # Ubuntu CI) and keep the background loop disarmed. A test opts in with
    # macos_contacts.configure(fake_snapshot=...), which short-circuits before
    # any disk/platform logic.
    macos_contacts.configure(platform="linux")
    contacts_sync.configure(None)
    _prev_contacts_sync_enabled = settings.contacts_sync_enabled
    settings.contacts_sync_enabled = False
    yield
    llm.configure()
    memory_engine.configure("unset")
    food_db.configure("unset")
    reminders.configure("unset")
    providers.configure("unset")
    fitness_sync.configure("unset")
    email_triage.configure("unset")
    email_sync.configure("unset")
    email_draft.configure("unset")
    moodle_sync.configure("unset")
    finance_sync.configure("unset")
    macos_contacts.configure()          # reset to real detection
    contacts_sync.configure("unset")
    settings.contacts_sync_enabled = _prev_contacts_sync_enabled
```

3c. Add a temp-roots fixture next to `attachments_tmpdir`, so extracted photos
and the App-Support root land in per-test scratch space, never `~/Library` or
`./data` (mirrors the attachments fixture; photos resolve under
`settings.app_support_dir/contact_photos`):
```python
@pytest.fixture(autouse=True)
def contacts_photos_tmpdir(tmp_path):
    """Contact photos + the App Support root live in per-test scratch, never the
    real ~/Library/Application Support or ./data."""
    prev_support = settings.app_support_dir
    prev_photos = settings.contacts_photos_dir
    settings.app_support_dir = str(tmp_path / "AppSupport")
    settings.contacts_photos_dir = "contact_photos"     # relative -> resolved under App Support
    yield
    settings.app_support_dir = prev_support
    settings.contacts_photos_dir = prev_photos
```

- [ ] **Step 4: Run the guard test to verify it passes**

```
cd backend && .venv/bin/python -m pytest tests/test_contacts_ci.py::test_real_contacts_probing_disabled_by_default -q
```
Expected: PASS.

- [ ] **Step 5: Add the deployment-aware integration tests** — append to `backend/tests/test_contacts_ci.py`

```python
def test_remote_postgres_dsn_is_accepted_with_tls():
    """A remote/self-hosted PostgreSQL DSN is a SUPPORTED deployment. make_engine
    must accept it (lazily, no connection) — it is NEVER refused as 'not local'.
    Persistence may be remote; auth_kind='local' describes the SOURCE, not
    residency. (There is intentionally no remote-DSN-refusal test; if a prior
    revision added one, delete it.)"""
    dsn = ("postgresql://appuser:secret@db.us-east-1.pooler.example.com:5432/"
           "scuffedos?sslmode=require")
    engine = make_engine(dsn)
    try:
        assert engine.dialect.name == "postgresql"
    finally:
        engine.dispose()
    # A raw provider URL over a non-loopback host is normalized, not rejected.
    assert normalize_database_url(
        "postgres://u:p@10.0.0.9:5432/app?sslmode=require"
    ).startswith("postgresql+psycopg://")


def test_remote_postgres_outage_is_error_never_empty(monkeypatch):
    """An unreachable/erroring PostgreSQL server is a FAILED sync (status='error'),
    NEVER 'empty' — and it must not soft-delete existing rows. Guards the money-
    manufacturing-style bug where an outage looks like 'every contact deleted'."""
    store.set_contacts_enabled(True, region="US", now=NOW)
    macos_contacts.configure(fake_snapshot=_snap(
        SnapshotStatus.COMPLETE_NONEMPTY,
        [_person("A", "Ada", "+15550001111"), _person("B", "Bo", "+15550002222")]))
    first = contacts_sync.tick(NOW)
    assert first.status == "ok"
    assert len(store.list_people()["items"]) == 2

    # Now the database link drops during apply, while the reader still returns a
    # snapshot that happens to omit B (as if B were removed).
    def _boom(snapshot, now):
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))
    monkeypatch.setattr(store, "apply_contacts_snapshot", _boom)
    macos_contacts.configure(fake_snapshot=_snap(
        SnapshotStatus.COMPLETE_NONEMPTY, [_person("A", "Ada", "+15550001111")]))
    res = contacts_sync.tick(NOW)
    assert res.status == "error"
    assert res.last_error
    assert res.removed == 0
    # B was NOT soft-deleted — the failed apply never reconciled.
    assert len(store.list_people()["items"]) == 2


def test_db_error_mid_apply_rolls_back_atomically(monkeypatch):
    """A DB-level failure part-way through apply rolls the whole transaction back:
    no half-written rows survive, and pre-existing rows are untouched. (Infra
    errors are fatal — they must NOT be swallowed as a per-record 'partial'.)"""
    store.set_contacts_enabled(True, region="US", now=NOW)
    seed = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [_person("A", "Ada", "+15550001111"),
                  _person("B", "Bo", "+15550002222")])
    assert store.apply_contacts_snapshot(seed, NOW).status == "ok"

    import app.identity as identity
    real = identity.canon_handle

    def _drop_on_c(raw, region):
        if raw == "+15550009999":            # C's handle -> the link "drops"
            raise OperationalError("INSERT", {}, Exception("connection reset"))
        return real(raw, region)
    monkeypatch.setattr(identity, "canon_handle", _drop_on_c)

    bad = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                [_person("A", "Ada", "+15550001111"),
                 _person("B", "Bo", "+15550002222"),
                 _person("C", "Cy", "+15550009999")])
    with pytest.raises(OperationalError):
        store.apply_contacts_snapshot(bad, NOW)

    # Rolled back: C never landed, A/B unchanged, count still 2.
    names = {p["display_name"] for p in store.list_people()["items"]}
    assert names == {"Ada", "Bo"}


def test_partial_read_snapshot_never_reconciles():
    """A PARTIAL_READ snapshot (>=1 store failed) writes state only — no row
    writes, no soft-deletes — because reconciliation on an incomplete read would
    delete real contacts."""
    store.set_contacts_enabled(True, region="US", now=NOW)
    store.apply_contacts_snapshot(_snap(
        SnapshotStatus.COMPLETE_NONEMPTY,
        [_person("A", "Ada", "+15550001111"),
         _person("B", "Bo", "+15550002222")]), NOW)
    assert len(store.list_people()["items"]) == 2

    partial = ContactsSnapshot(status=SnapshotStatus.PARTIAL_READ, people=[],
                               stores_total=2, stores_read=1, store_ids=["local"])
    res = store.apply_contacts_snapshot(partial, NOW)
    assert res.status == "partial"
    assert res.removed == 0
    assert len(store.list_people()["items"]) == 2      # nothing deleted


def test_partial_upsert_failure_marks_partial_and_preserves_absent(monkeypatch):
    """A per-record failure inside a COMPLETE_* apply commits the good rows,
    records status='partial', and SKIPS reconciliation — so a contact absent from
    this snapshot is NOT soft-deleted (an incomplete apply must never delete)."""
    store.set_contacts_enabled(True, region="US", now=NOW)
    seed = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [_person("A", "Ada", "+15550001111"),
                  _person("D", "Di", "+15550003333")])
    store.apply_contacts_snapshot(seed, NOW)

    import app.identity as identity
    real = identity.canon_handle

    def _fail_on_b(raw, region):
        if raw == "+15550008888":            # only B's reindex explodes
            raise ValueError("bad handle transform")
        return real(raw, region)
    monkeypatch.setattr(identity, "canon_handle", _fail_on_b)

    # New snapshot: A stays, B is new-but-broken, C is new-and-fine; D is ABSENT.
    snap = _snap(SnapshotStatus.COMPLETE_NONEMPTY,
                 [_person("A", "Ada", "+15550001111"),
                  _person("B", "Bo", "+15550008888"),
                  _person("C", "Cy", "+15550004444")])
    res = store.apply_contacts_snapshot(snap, NOW)
    assert res.status == "partial"
    assert res.removed == 0                    # reconcile skipped
    names = {p["display_name"] for p in store.list_people()["items"]}
    assert "Ada" in names and "Cy" in names    # good upserts committed
    assert "Di" in names                       # absent D preserved, not soft-deleted


def test_overlapping_applies_serialize_under_the_lock(monkeypatch):
    """Two applies never interleave: the module process lock (plus, on Postgres,
    pg_advisory_xact_lock) serializes them, so the single shared SQLite connection
    is used one-at-a-time and no rows are corrupted. On the Postgres CI leg this
    same test exercises advisory-lock contention."""
    people = [_person(f"P{i}", f"Person {i}", f"+1555000{i:04d}") for i in range(4)]
    snap = _snap(SnapshotStatus.COMPLETE_NONEMPTY, people)

    import app.identity as identity
    real = identity.canon_handle
    gate = threading.Lock()
    live = {"n": 0, "max": 0}

    def _tracked(raw, region):
        with gate:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        time.sleep(0.02)
        with gate:
            live["n"] -= 1
        return real(raw, region)
    monkeypatch.setattr(identity, "canon_handle", _tracked)

    errors: list[BaseException] = []

    def _worker():
        try:
            store.apply_contacts_snapshot(snap, NOW)
        except BaseException as exc:          # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []                        # no "database is locked" / cursor races
    assert live["max"] == 1                     # applies never overlapped
    assert len(store.list_people()["items"]) == 4        # every person landed, none dropped
```

- [ ] **Step 6: Run the integration tests to verify they pass (both DB legs)**

```
cd backend && .venv/bin/python -m pytest tests/test_contacts_ci.py -q
cd backend && TEST_DATABASE_URL= .venv/bin/python -m pytest tests/test_contacts_ci.py -q
```
Expected: PASS on both the configured Postgres backend and the SQLite leg. (If a
local Postgres is unavailable, the SQLite leg alone must pass; note the skip.)

- [ ] **Step 7: Extend the canonical migration lock** — `backend/tests/test_migrations.py`

7a. Add the three new tables to the shared `ALL_TABLES` set (used by both the
upgrade and the downgrade tests, so upgrade + downgrade coverage is automatic):
```python
    "finance_recurring", "finance_liabilities", "finance_investment_transactions",
    "people", "person_handle", "contacts_sync_state",
}
```

7b. Extend `test_upgrade_head_builds_full_schema` with column, index, and
constraint assertions for the people domain (migration `0010`, Task 2). Append
before `engine.dispose()`:
```python
    person_cols = {c["name"] for c in inspect(engine).get_columns("people")}
    assert {"owner", "source", "source_id", "display_name", "first_name",
            "last_name", "nickname", "organization", "job_title", "phones",
            "emails", "photo_key", "has_photo", "relationship",
            "relationship_strength", "notes", "pinned", "last_contacted_at",
            "removed_from_source_at", "meta", "created_at", "updated_at"} <= person_cols

    handle_cols = {c["name"] for c in inspect(engine).get_columns("person_handle")}
    assert {"owner", "person_id", "kind", "value", "possible",
            "created_at"} <= handle_cols

    state_cols = {c["name"] for c in inspect(engine).get_columns("contacts_sync_state")}
    assert {"owner", "enabled", "status", "access", "normalization_region",
            "last_sync_at", "last_error", "enabled_at", "created_at",
            "updated_at"} <= state_cols

    # Idempotent-upsert + resolve integrity: the composite/unique keys exist.
    people_uqs = {tuple(uc["column_names"])
                  for uc in inspect(engine).get_unique_constraints("people")}
    assert ("owner", "source", "source_id") in people_uqs
    handle_uqs = {tuple(uc["column_names"])
                  for uc in inspect(engine).get_unique_constraints("person_handle")}
    assert ("person_id", "kind", "value") in handle_uqs
    state_uqs = {tuple(uc["column_names"])
                 for uc in inspect(engine).get_unique_constraints("contacts_sync_state")}
    assert ("owner",) in state_uqs             # one consent row per owner

    # Handle lookup + FK cleanup are indexed for resolve_handle.
    handle_idx_cols = {tuple(ix["column_names"])
                       for ix in inspect(engine).get_indexes("person_handle")}
    assert ("value",) in handle_idx_cols
    assert ("person_id",) in handle_idx_cols
```

`test_downgrade_base_removes_everything` needs no edit — it asserts
`not ALL_TABLES & tables`, so it now proves `0010`'s `downgrade()` drops all three
tables in reverse dependency order. The Postgres-only
`test_migrations_build_models_schema_on_postgres` also picks up the new tables for
free (it diffs `Base.metadata` against the migrated schema).

- [ ] **Step 8: Run the migration tests (both legs)**

```
cd backend && .venv/bin/python -m pytest tests/test_migrations.py -q
cd backend && TEST_DATABASE_URL= .venv/bin/python -m pytest tests/test_migrations.py -q
```
Expected: PASS. On the Postgres leg, `test_migrations_build_models_schema_on_postgres` confirms models and `0010` have not drifted.

- [ ] **Step 9: Lock the five-card connector order with a deterministic probe** — `backend/tests/test_connectors.py`

The autouse Contacts seam forces `platform="linux"`, so `macos_contacts.is_supported()`
returns `False` and `_configured("macos_contacts")` is `False` deterministically —
identical on macOS and CI. An unsupported host never probes, so `_contacts_connector`
short-circuits `access` to `"unknown"` (the frontend renders that as `unsupported`).
Update the exact order/auth-kind lock and add the fifth-card status assertion:
```python
def test_all_five_present_not_connected_on_empty_db(client):
    body = client.get("/api/connectors").json()
    assert [c["name"] for c in body] == [
        "google", "whoop", "moodle", "plaid", "macos_contacts"]
    assert [c["auth_kind"] for c in body] == [
        "oauth", "oauth", "token", "link", "local"]
    for c in body:
        assert c["status"] == "not_connected"
        assert c["connected_at"] is None
        assert c["items"] == []


def test_contacts_card_access_is_deterministic_off_darwin(client):
    # Autouse seam forces platform='linux' -> is_supported() False on macOS + CI
    # alike; an unsupported host is never probed, so access short-circuits to
    # 'unknown' (frontend renders 'unsupported'), never the host's real FDA state.
    card = next(c for c in client.get("/api/connectors").json()
               if c["name"] == "macos_contacts")
    assert card["auth_kind"] == "local"
    assert card["configured"] is False         # seam is_supported() False off darwin
    assert card["access"] == "unknown"         # unsupported host is not probed
    assert card["status"] == "not_connected"


def test_contacts_card_granted_when_reader_reports_a_store(client):
    # Opt in deterministically (host-independent): platform="darwin" drives the
    # seam's is_supported() -> True (so configured=True) on macOS dev + CI alike,
    # and a fake COMPLETE snapshot makes probe_access() derive 'granted'. Consent
    # (store.set_contacts_enabled) is the SEPARATE gate for status='connected'.
    from app.providers import macos_contacts
    from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus
    from app.providers.base import NormalizedPerson
    macos_contacts.configure(platform="darwin", fake_snapshot=ContactsSnapshot(
        status=SnapshotStatus.COMPLETE_NONEMPTY,
        people=[NormalizedPerson(source="macos_contacts", source_id="A",
                                 display_name="Ada")],
        stores_total=1, stores_read=1, store_ids=["local"]))
    store.set_contacts_enabled(True, region="US")
    card = next(c for c in client.get("/api/connectors").json()
               if c["name"] == "macos_contacts")
    assert card["configured"] is True          # seam-driven, not host sys.platform
    assert card["access"] == "granted"
    assert card["status"] == "connected"
```
Replace the old `test_all_four_present_not_connected_on_empty_db` with the
five-card version above. If Task 8 already added a `test_connectors_contacts.py`,
delete the duplicated assertions here and keep the order/auth-kind lock as the
single source of truth for card ordering.

- [ ] **Step 10: Run the connector tests**

```
cd backend && .venv/bin/python -m pytest tests/test_connectors.py -q
```
Expected: PASS.

- [ ] **Step 11: Add the manual signed-package acceptance checklist** — `backend/tests/test_macos_contacts_acceptance.py`

These four checks can only pass on a **signed, packaged** ScuffedOS build with
Full Disk Access granted to the app bundle — they cannot run under `tauri dev`,
CI, or a bare `python` process (which has no responsible-process attribution).
They are collected but skipped so the intent stays in the suite and the count is
stable.

```python
"""Manual, on-hardware acceptance for the signed macOS package (M10 s1).

Run by hand on a signed, notarized ScuffedOS.app with Full Disk Access granted to
the BUNDLE (not to your terminal). These are skipped in CI and `tauri dev`: the
TCC responsible-process is the app bundle, System Settings deep links only open a
real settings pane, and the live AddressBook uses WAL so a private snapshot must
include -wal/-shm. Flip RUN_MACOS_ACCEPTANCE=1 on the target machine to run them.
"""
import os

import pytest

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        os.environ.get("RUN_MACOS_ACCEPTANCE") != "1",
        reason="manual: signed macOS bundle + Full Disk Access only (not CI/tauri dev)",
    ),
]


def test_fda_responsible_process_is_the_signed_bundle():
    """With FDA granted to ScuffedOS.app, probe_access() -> 'granted' from inside
    the bundle; granting FDA to Terminal alone must NOT satisfy it."""
    from app.providers import macos_contacts
    macos_contacts.configure()                 # real detection
    assert macos_contacts.probe_access() == "granted"


def test_system_settings_deep_link_opens_full_disk_access():
    """The 'Grant Full Disk Access' button opens the Privacy_AllFiles pane. Verify
    manually that the pane appears with ScuffedOS listed."""
    import subprocess
    url = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    assert subprocess.run(["open", url]).returncode == 0


def test_live_wal_read_returns_current_contacts():
    """Against the real, actively-written AddressBook (WAL mode), a full sync reads
    a non-empty COMPLETE snapshot including a contact you edited seconds earlier."""
    from app.providers import macos_contacts
    from app.providers.macos_contacts import SnapshotStatus
    macos_contacts.configure()
    from app.config import settings
    snap = macos_contacts.read_snapshot(
        region=settings.contacts_default_region,
        photos_dir=os.path.expanduser(settings.contacts_photos_dir))
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.people


def test_photos_land_under_app_support_not_repo():
    """Extracted photos are written under the App Support contact_photos root, with
    a detected media type, never in the repo/./data."""
    from app.config import settings
    root = os.path.join(os.path.expanduser(settings.app_support_dir), "contact_photos")
    assert os.path.isdir(root)
    files = os.listdir(root)
    assert any(f.split(".")[-1] in {"jpg", "jpeg", "png", "heic"} for f in files)
```

Register the marker so pytest does not warn — `backend/pytest.ini`:
```ini
[pytest]
testpaths = tests
addopts = -q
markers =
    manual: on-hardware checks that require a signed macOS bundle + FDA (skipped in CI)
```

- [ ] **Step 12: Full suite (both DB legs) + commit**

```
cd backend && .venv/bin/python -m pytest
cd backend && TEST_DATABASE_URL= .venv/bin/python -m pytest -q
```
Report the count. Baseline before this slice was **703 collected**; report the new
collected/passed total (the four manual checks show as skipped, not failures).
```bash
git add backend/tests/conftest.py backend/tests/test_contacts_ci.py \
        backend/tests/test_migrations.py backend/tests/test_connectors.py \
        backend/tests/test_macos_contacts_acceptance.py backend/pytest.ini
git commit -m "test(people): CI hardening — offline Contacts seam, remote-outage/rollback/partial/lock integration, migration+connector locks, manual acceptance (M10 s1)"
```

---

## Task 11: Docs + privacy (deployment-aware, third-party-PII honest)

Update the docs to the corrected persistence model (structured contact fields go
to the **configured PostgreSQL database, which may be remote/self-hosted**;
photos stay on the backend host), disclose that imported Contacts are
**third-party PII**, and remove the stale "Supabase" naming and the "no data
about anyone other than the user" claim from the privacy surface. Then publish.

**Files:**
- Modify: `docs/people.md` (bring the existing planning doc to the shipped design — do NOT recreate it)
- Modify: `docs/privacy-policy.md` (canonical policy: storage wording, third-party-PII, Contacts disclosure, effective date)
- Modify: `README.md` (connector list + persistence wording)
- Modify: `docs/README.md` (provider summary line naming Supabase)
- Then: run the `publish-privacy-policy` skill to mirror the canonical policy to the gist + corp site.

**Interfaces:** documentation only; no code signatures. References the shipped
surfaces: `POST /api/people/contacts/enable|disconnect|forget`,
`POST /api/people/sync`, `GET /api/people/{id}/photo`, `resolve_handle`,
`contacts_default_region`, `contacts_sync_seconds`, `contacts_photos_dir`,
`app_support_dir` (Tasks 3–8).

- [ ] **Step 1: Rewrite `docs/people.md`** to the shipped design (modify the existing file — keep its title + the cross-links that still apply). Replace the "Current state / prototype" sections with:

  - **Model** — `people` (identity fields; `phones`/`emails` as `[{value,label,normalized}]`; CRM-native `relationship`/`relationship_strength`/`notes`/`pinned`/`last_contacted_at`; `removed_from_source_at`; `photo_key`), `person_handle` (normalized handle index), `contacts_sync_state` (one consent row per owner). Keyed `(owner, source, source_id)`.
  - **Persistence** — structured contact fields are written to **the configured PostgreSQL database, which may run locally (loopback) or on a remote/self-hosted server; when it is remote, contact data travels over the network to that server** (TLS required for any non-loopback DSN). Extracted **photos remain on the backend host** under `app_support_dir/contact_photos` (never in PostgreSQL, never in the repo). Single backend host per database in this slice.
  - **One-way, read-only import** — the macOS AddressBook is read locally, read-only (`mode=ro` + `PRAGMA query_only=ON` + a bounded read transaction), and is **never written back**. Sync writes only sync-owned identity fields; CRM-native fields are ScuffedOS-owned and untouched by sync.
  - **Consent + FDA lifecycle** — import defaults **disabled**; app consent (`enabled`) is tracked **separately** from Full Disk Access. Document `enable` (requires the storage disclosure acknowledged; stamps `normalization_region`; kicks a sync), `disconnect` (stops syncing, keeps rows), `forget` (confirmed; deletes imported rows + handles + photos, converting CRM-annotated people to a `manual` tombstone), and **FDA-revoked → status `stale`, rows preserved**.
  - **Complete-snapshot sync** — soft-deletion reconciliation runs **only** on a `COMPLETE_*` snapshot with no per-record error; failed/partial/denied/unsupported reads never soft-delete; an unreachable PostgreSQL server is a **failed sync (`error`), never an empty source**.
  - **`resolve_handle`** — canonicalizes with the **persisted** `normalization_region` and returns a **list** (shared handles → multiple people; includes soft-deleted), for the iMessage slice.
  - **Config** — `contacts_sync_enabled`, `contacts_sync_seconds`, `contacts_default_region`, `contacts_photos_dir`, `app_support_dir`.
  - **No AI** — this slice sends Contacts to no AI providers and no third-party Contacts APIs.

  Update the doc's status line to `Status: implemented (M10 s1)` and the "Last updated" date to 2026-07-13; drop the `Owner: TBD`.

- [ ] **Step 2: Update `docs/privacy-policy.md`** (canonical source — the gist and corp site are mirrors). Concrete edits:

  - **§1 "What we do not collect."** The claim *"We do not collect data about anyone other than the user of the app."* is now false — imported Contacts are third-party PII. Replace with wording that scopes it: ScuffedOS has no advertising/analytics/tracking and collects no data about non-users **except** the contact details the user chooses to import from their own macOS Contacts (names, phone numbers, email addresses, organization/title, and photos), which describe the user's own contacts and are used only to power the user's CRM and messaging features.
  - **§1 "Connected service data"** — add a Contacts sentence: *If you enable macOS Contacts, ScuffedOS reads your local Contacts (AddressBook) database read-only after you grant the app Full Disk Access and acknowledge the storage disclosure; it stores contact names, phone numbers, email addresses, organization and job title, and contact photos. It never writes back to your Contacts and sends Contacts to no AI provider.*
  - **§3 service-providers table** — **remove the `Supabase` row** and replace the storage description with a deployment-neutral row: `**PostgreSQL database (the configured server)** | Structured app data storage | Tasks, events, habits, nutrition logs, conversations, memories and embeddings, synced WHOOP/finance/Moodle data, email metadata, and imported contact fields (names, phone numbers, emails, organization/title). The database may run locally or on a remote/self-hosted server; when remote, this data is transmitted to that server over TLS. Contact photos are NOT stored here — they stay on the backend host.` Also delete "on-device" from the notifications sentence (say notifications are generated locally on the backend host).
  - **§4** — add a **"macOS Contacts"** subsection paralleling WHOOP/Gmail: read only after explicit app consent **and** Full Disk Access; local read-only, one-way, never written back; stored in the configured PostgreSQL database (may be remote — transmitted over TLS) with photos on the backend host; **sent to no AI provider and no third-party Contacts API**; **revocation** = revoke Full Disk Access in System Settings and/or **Disconnect** in ScuffedOS (stops syncing, keeps existing CRM data) or **Forget imported data** (deletes imported contacts, handles, and photos); **retention** = imported data persists until you Forget it or delete individual people; a **stale** state appears if access is later revoked, and existing rows are preserved rather than deleted.
  - **§5 "Data storage and security"** — replace *"App data is stored in a Postgres database hosted by Supabase; attachments and the memory history file are stored on the operator's machine."* with *"App data is stored in the configured PostgreSQL database, which may run locally or on a remote/self-hosted server; attachments, the memory history file, and imported contact photos are stored on the backend host running the app."* Keep the TLS-in-transit bullet and add: *a non-loopback database connection requires TLS (`sslmode=require` or stronger); connection strings and credentials are never written to logs.*
  - **§6 retention/§7 rights** — note disconnecting/Forgetting macOS Contacts deletes imported contact data as in §4.
  - **Effective date** at the top → **July 13, 2026**.

- [ ] **Step 3: Scrub the remaining "Supabase" naming from repo prose** (contract bans the term). Replace the storage naming with "the configured PostgreSQL database (may be remote/self-hosted)" in:
  - `README.md` line ~102: change *"Data persists in Postgres (Supabase free tier in production, any Postgres or SQLite-for-tests locally)"* → *"Data persists in the configured PostgreSQL database (local or remote/self-hosted; SQLite for tests)"*.
  - `docs/README.md` line ~44: drop `Supabase` from the parenthetical provider list in the privacy-policy row (it now reads "the configured PostgreSQL database").

  (Historical architecture decision records — `docs/architecture-review.md`,
  `docs/data-store.md`, `docs/memory.md`, `docs/backend-overview.md` — are dated
  ADRs that record the *2026-06-10 hosting decision*; leave those historical
  notes intact. This step scrubs only the **current** privacy/README claims.)

- [ ] **Step 4: Add the connector to `README.md`.** Update the Notes line that lists connectors ("Whoop in M4, Plaid in M6; Email and People follow in M5") to note People/CRM + macOS Contacts (local, Full-Disk-Access) landed in M10 s1, and add "Apple Contacts (local)" wherever the connector set is enumerated.

- [ ] **Step 5: Commit the canonical revision**

```bash
git add docs/people.md docs/privacy-policy.md README.md docs/README.md
git commit -m "docs(people): shipped People/CRM doc + deployment-aware privacy disclosure (remote PostgreSQL, third-party Contacts PII), scrub Supabase naming (M10 s1)"
```

- [ ] **Step 6: Publish the privacy policy** — invoke the `publish-privacy-policy` skill (canonical `docs/privacy-policy.md` changed, so its two mirrors are stale). It syncs the public GitHub gist and the scuffed-corporation website `/privacy/` page and carries the bumped effective date live. Confirm both mirrors updated. Publishing to the public gist/site is a user-visible action — confirm before the skill pushes.

---

## Self-Review (coverage → task, with acceptance criteria)

Design reference: [`docs/superpowers/specs/2026-07-13-people-crm-contacts-slice1-design.md`](../specs/2026-07-13-people-crm-contacts-slice1-design.md) (this slice's design spec). Each row states the acceptance criterion so the mapping is self-contained.

| Concern (rev-2 contract area / spec section) | Task(s) | Acceptance criterion (how we know it's done) |
| --- | --- | --- |
| **1. Architecture & persistence corrected** — `auth_kind="local"` = source/mechanism, not residency; structured fields → configured PostgreSQL (may be remote); TLS on non-loopback; no secrets in logs; single host | 7, 8, 11 | No "on-device/all-local/zero-egress/Supabase" anywhere; remote DSN accepted (`test_remote_postgres_dsn_is_accepted_with_tls`); TLS-required + no-DSN-in-logs stated in config/db layer and privacy §5 |
| **2. Consent + FDA lifecycle** — default disabled; consent vs FDA separated; pre-enable storage disclosure; disconnect ≠ delete; confirmed forget w/ CRM-native tombstone survival; FDA-revoke → stale | 2, 3, 7, 9 | `contacts_sync_state.enabled` defaults `False`; enable gated on disclosure ack; disconnect keeps rows; forget converts CRM-annotated people to `manual` tombstones; denied read → `stale`, rows preserved (`test_partial_read_snapshot_never_reconciles`, denied-preservation in Task 3) |
| **3. Complete-snapshot sync** — structured reader statuses; never `[]` for missing entity; all stores read before reconcile; single transactional apply; skip reconcile on incompleteness; process + advisory lock; `SyncResult`; remote outage = failed not empty | 3, 4, 6, 10 | `apply_contacts_snapshot` reconciles only on `COMPLETE_*` w/ no per-record error; `test_remote_postgres_outage_is_error_never_empty`, `test_db_error_mid_apply_rolls_back_atomically`, `test_overlapping_applies_serialize_under_the_lock` |
| **4. Hardened reader** — no `immutable=1` on live reads; real table/column probing; distinguish FDA/unsupported/corruption/missing/IO; namespaced+hashed source ids (never `zpk:1`); multi-store union w/ unique 2nd-store contact | 4 | `read_snapshot` returns each `SnapshotStatus`; `mode=ro`+`query_only`+read txn+`busy_timeout`; `source_id = sha1(store_id:zuniqueid…)` in `String(128)`; multi-store fixture asserts the 2nd store's unique contact imported |
| **5. Store + identity** — idempotent (normalize copies before assigning JSON, no post-flush mutation); fresh-session assertion; handle add/remove/dupe/shared/resurrection; canon matrix; persisted region | 1, 3 | Canonicalization matrix (international/national/short/malformed/unicode/region-change) passes; re-upsert updates in place; omitting a handle removes its index row; `resolve_handle` uses persisted `normalization_region` |
| **6. Source-aware CRUD** — imported identity read-only; CRM-native editable; hard delete only `manual` (else tombstone); typed `PhoneEntry`/`EmailEntry`; trim/bound; strength 1–5; reject null-for-non-null; deterministic sort + search + cursor pagination | 3, 7 | PATCH of imported identity fields rejected/ignored; CRM-native PATCH applies; delete of imported → tombstone; `PersonOut.phones: list[PhoneEntry]`; `GET /api/people?q=&cursor=` returns `{items, next_cursor}` |
| **7. Photos** — App-Support root; opaque relative `photo_key`; hashed + atomic write; containment/symlink guard; failure isolation; media-type detection; cleanup; served via API base + initials fallback | 5, 7, 9 | Photos under `app_support_dir/contact_photos`; `photo_key = sha256(store_id:source_id).<ext>`; `os.replace` atomic; `GET /api/people/{id}/photo` containment-checked with detected `image/<type>`; a photo failure never aborts the snapshot; superseded files cleaned on re-sync/forget/delete |
| **8. Frontend** — usable CRM (not directory-only); status model; refetch triggers; controlled search; local card exempt from credential gates; access states rendered separately; pre-enable disclosure; awaited refresh; a11y; automated tests | 9 | `CRMScreen`/`ConnectorsPanel` render first-sync/syncing/denied/stale/empty/no-match distinctly; Vitest + RTL tests for the CRM loading→empty and the local-card denied→Grant + disclosure-gated enable |
| **9. Tests / CI** — shared fixtures; platform/probe injection; global disable of real probing + bg sync; temp photo roots; remote-outage/rollback/partial/overlap/lock-contention; remote-DSN-allowed replaces refusal; migration + `ALL_TABLES` for 3 tables; deterministic connector order; `.venv/bin/python -m pytest`; baseline 703; signed-package acceptance | 10 | This task — `conftest.py` seam, `test_contacts_ci.py`, extended `test_migrations.py`/`test_connectors.py`, manual `test_macos_contacts_acceptance.py` |
| **10. Docs / privacy** — modify (not recreate) `people.md`; remove Supabase; configured PostgreSQL (may be remote); third-party-PII claim corrected; full disclosure set; README; publish workflow; real spec link | 11 | This task — `people.md`, `privacy-policy.md`, `README.md`, `docs/README.md` edited + `publish-privacy-policy` run |

**Deferred (not in this slice, per the design spec):** cross-source dedup via `ZLINKID`; contact → message timeline; two-way editing; multi-host / shared-database photo storage + distributed sync lease; the on-hardware FDA responsible-process acceptance run (kept as the manual, skipped `test_macos_contacts_acceptance.py` — cannot run in CI or `tauri dev`).

## Preserved foundations

Concrete mechanisms carried over from rev 1 (they were right; rev 2 only adapts their surface to the contract):

- **Owner scoping** — every `people`/`person_handle`/`contacts_sync_state` row carries `owner`, stamped `owner=settings.owner` and filtered on every query (Task 2 models, Task 3 store).
- **CRM-field ownership during sync** — sync writes only the sync-owned identity fields; `relationship`, `relationship_strength`, `notes`, `pinned`, `last_contacted_at` are ScuffedOS-owned and never touched by `apply_contacts_snapshot` (Task 3).
- **Soft-delete resurrection** — a contact absent from a `COMPLETE_*` snapshot is soft-deleted (`removed_from_source_at`), never hard-deleted; a returning contact clears the flag on re-upsert (Task 3).
- **Multi-match handle resolution** — `resolve_handle(handle) -> list[dict]` returns every person carrying a shared handle (ordered most-recently-contacted, includes soft-deleted), rather than a single row (Task 3), for the iMessage slice.
- **Dynamic entity-number discovery** — the reader resolves the `ABCDContact` entity via `Z_PRIMARYKEY` at runtime and never hardcodes `Z_ENT`, so the fixture DB uses an arbitrary non-1 value to prove it (Task 4).
- **Group exclusion** — `ABCDGroup`/non-contact entities are excluded from the import so groups never surface as people (Task 4).
- **One-way, read-only AddressBook access** — the AddressBook stores are opened read-only (`mode=ro` + `PRAGMA query_only=ON` + a bounded read transaction) and are never written back (Task 4).
