# Messaging M10 — Slice 1: People/CRM backend + macOS Contacts sync (design)

**Status:** design, approved for spec-writing 2026-07-13.
**Slice 1 of the Messaging initiative** (iMessage first; WhatsApp deferred). This slice does **not** touch iMessage yet — it builds the People/CRM backend and populates it from macOS Contacts, and it establishes the Full Disk Access (FDA) grant and the `resolve_handle()` seam that the iMessage slice will consume.

Related brainstorm decisions are recorded in §2. The broader messaging arc (read → send → AI) is in §11.

---

## 1. Goals & non-goals

### Goals
- Turn the **People** screen from a hardcoded stub (`frontend/src/screens/CRMScreen.jsx`, three sample arrays, no backend) into a **real, DB-backed CRM**.
- Sync the user's **macOS Contacts** (AddressBook) into `Person` records, keyed by source so a re-sync is idempotent and **never clobbers manual edits**.
- Establish the **Full Disk Access** connect flow (a new `local` connector kind) — the same grant the iMessage slice reuses.
- Ship a `resolve_handle(phone_or_email) -> Person | None` store seam for the next slice.
- Everything stays **on-device**: Contacts data lives only in the app-managed local Postgres; nothing leaves the machine.

### Non-goals (this slice)
- No iMessage / `chat.db` reads (Slice 2).
- No sending anything (Slices 3–4). But the **no-auto-send governing principle** (§2.G) is written into the design now.
- No contact **editing pushed back** to macOS Contacts — this is a **one-way import** (macOS → ScuffedOS). We never write to the AddressBook DB.
- No cross-source de-duplication / contact merging (a person appearing in both iCloud and On-My-Mac stays two `source_id`s for now — see §10 future work).

---

## 2. Ratified decisions (from brainstorming)

- **A. Messaging = iMessage first, WhatsApp dropped.** WhatsApp has no sanctioned personal-chat API; the linked-device libraries (Baileys / whatsapp-web.js) carry a real ban risk. Deferred, revisit later.
- **B. Slice order re-cut.** People/CRM has no backend at all, but "sync Contacts into the CRM" needs one — so **People/CRM + Contacts is Slice 1**, iMessage reader is Slice 2. The FDA grant built here is reused by Slice 2.
- **C. Name resolution = Contacts **and** CRM.** macOS Contacts syncs *into* People/CRM; People/CRM is then the single source of truth that iMessage handle-resolution joins against.
- **D. Contacts read = raw AddressBook SQLite under FDA** (not `Contacts.framework`/CNContact). Rationale in §6.
- **E. Phone canonicalization = bundle `phonenumberslite`** (§4.3).
- **F. History/scope defaults** (carried from the messaging brainstorm, apply to later slices): iMessage backfill capped at 12 months (configurable), include SMS/RCS + group chats, inline attachment previews. **Not in this slice.**
- **G. No auto-send, ever (governing principle).** Every future outbound message requires explicit per-message user approval. Drafts are staged; a human confirms each send; no setting can enable auto-send. Hard architectural gate, documented now, enforced in Slices 3–4.

---

## 3. Where this sits (topology)

```
macOS Contacts.app  ──writes──▶  ~/Library/Application Support/AddressBook/
                                   ├─ AddressBook-v22.abcddb            (top-level/local store)
                                   └─ Sources/<UUID>/AddressBook-v22.abcddb   (one per account: iCloud, On-My-Mac, Exchange…)
                                        (all TCC-protected → need Full Disk Access)
                                             │  read-only, immutable
                                             ▼
ScuffedOS.app (Tauri, signed)  ──spawns──▶  scuffedos-backend (Python sidecar)
   user grants FDA to the .app                 │  inherits the app's FDA (responsible-process rule, §6)
                                               ▼
                                   providers/macos_contacts.py  ──▶  contacts_sync.py  ──▶  store.upsert_person(...)
                                               │                                              │
                                               ▼                                              ▼
                                       identity.py (canonicalize                     local Postgres  (Person rows)
                                        phones/emails)                                        │
                                                                                              ▼
                                   routers/people.py  ──▶  frontend CRMScreen (real data)
                                                          + Settings › Connectors card ("macOS Contacts", auth_kind=local)
                                   store.resolve_handle(handle) ──▶ (seam consumed by Slice 2 iMessage)
```

---

## 4. Components

### 4.1 `Person` model — new (`backend/app/models.py`)
Template = the `Email` model (`models.py:328`), which is the cleanest `(owner, source, source_id)` example.

Columns:
- `id` (PK), `owner: str = "me"` (indexed).
- `source: str` — `'macos_contacts'` | `'manual'`.
- `source_id: str` — for synced rows, `"<container-key>:<ZUNIQUEID>"` (per §4.2, `ZUNIQUEID` is only stable *within* a source DB, so it's paired with the source container to be globally unique within our DB); for `manual`, a generated uuid.
- `UniqueConstraint("owner","source","source_id", name="uq_people_owner_source_source_id")` → idempotent upsert.
- Identity: `display_name`, `first_name`, `last_name`, `nickname`, `organization`, `job_title`.
- `phones: JSONField` — list of `{value, label, normalized}` (see §4.3 for `normalized`).
- `emails: JSONField` — list of `{value, label, normalized}`.
- `photo_path: str | None` — path to an extracted JPEG in app storage (§4.4); `has_photo: bool` is always set (real photo present vs. initials fallback).
- **CRM-native fields, never overwritten by sync:** `relationship: str | None`, `relationship_strength: int | None` (0–5), `notes: str | None`, `last_contacted_at: datetime | None`, `pinned: bool = False`.
- `meta: JSONField` — birthday, source container UUID, raw label extras, `is_company` flag, `z_link_id` (Apple's cross-source unified-contact link, kept for future dedup).
- `created_at` / `updated_at` (`default=utcnow, onupdate=utcnow`).

`phones`/`emails` as JSON arrays follows the repo convention (`JSONField` at `models.py:27`; no child-table pattern exists anywhere). `photo_path` as a path string (not a blob) matches the files-metadata convention.

### 4.2 macOS Contacts reader — new (`backend/app/providers/macos_contacts.py`)
Pure, testable reader. **Takes an injectable root path** (`addressbook_root`, default `~/Library/Application Support/AddressBook`) so tests point at a fixture tree. Verified against a real on-disk `CREATE TABLE` dump (adversarial verification = CONFIRMED).

Algorithm:
1. **Enumerate stores** — union of the top-level `AddressBook-v22.abcddb` **plus** `glob("Sources/*/AddressBook-v22.abcddb")`. Each source (iCloud / On-My-Mac / Exchange / CardDAV) is a complete DB of identical schema; a contact (and its photo) lives only in its own source DB. The `Sources/<UUID>` folder name is the container key used in `source_id`.
2. **Open read-only + immutable** via SQLite URI `file:<path>?mode=ro&immutable=1` — never locks the live store, tolerates the `-wal`/`-shm` sidecar files. Never write, never copy-with-partial-WAL.
3. **Resolve entity id at runtime** — `SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME='ABCDContact'`; filter `ZABCDRECORD.Z_ENT = ?`. **Do not hardcode `22`** — the entity number varies by DB/version. This also excludes groups (`ABCDGroup`), which share `ZABCDRECORD`.
4. **Contact rows** — `ZABCDRECORD`: `Z_PK`, `ZUNIQUEID`, `ZFIRSTNAME`, `ZMIDDLENAME`, `ZLASTNAME`, `ZNICKNAME`, `ZORGANIZATION`, `ZJOBTITLE`, `ZTITLE` (name prefix — there is no `ZPREFIX`), `ZBIRTHDAY`, `ZDISPLAYFLAGS`, `ZTHUMBNAILIMAGEDATA` (photo, §4.4).
5. **Phones** — `ZABCDPHONENUMBER` join `ZOWNER = ZABCDRECORD.Z_PK`: `ZFULLNUMBER`, `ZLABEL`, `ZORDERINGINDEX` (preserve order). (Join on the generic `ZOWNER`, not `Z22_OWNER`.)
6. **Emails** — `ZABCDEMAILADDRESS` join `ZOWNER = Z_PK`: `ZADDRESS`, `ZADDRESSNORMALIZED` (Apple's own lowercased form — a useful cross-check), `ZLABEL`, `ZORDERINGINDEX`.
7. **Label unwrap** — standard labels are wrapped `_$!<Home>!$_` / `_$!<Work>!$_` / `_$!<Mobile>!$_` / `_$!<iPhone>!$_`; strip the `_$!<` … `>!$_` wrapper. Custom labels are stored plain.
8. **Dates** — Core Data absolute time = seconds since 2001-01-01; `unix = value + 978307200`. Birthday may be NULL / yearless (`ZBIRTHDAYYEARLESS`).
9. **Company rows** — `ZDISPLAYFLAGS` bit 0 = "show as company"; **treat NULL as not-company**.
10. Emit a normalized `ContactRecord` dataclass per contact (vendor field names confined to this file), consumed by the sync engine.

Also read (nice-to-have, low cost): `ZABCDMESSAGINGADDRESS` (`ZADDRESS`, `ZSERVICE`) — a contact's stored iMessage/other messaging handles. Storing these in `meta.messaging_handles` gives the iMessage slice a second resolution path. Optional; behind the same read.

We deliberately do **not** map `ZABCDRELATEDNAME` (macOS "Related Names" like Sister/Assistant) onto the CRM-native `relationship` field — that keeps the ownership line clean (`relationship` is ScuffedOS-owned, never seeded by sync). If ever wanted, raw related-names go in `meta`, untouched by the CRM layer.

### 4.3 Identity canonicalization — new (`backend/app/identity.py`)
The shared normalizer used by both the Contacts importer (to fill `normalized`) and the future `resolve_handle`. **New dependency: `phonenumberslite`** (pure-Python, 473 KB wheel / 5.2 MB installed, zero runtime deps, verified offline on Python 3.14.4 — vendors with no native build step). Full `phonenumbers` is avoided (~20 MiB of geocoder/carrier/timezone we don't need).

- `canon_phone(raw, default_region) -> {normalized, possible}`:
  - `n = phonenumbers.parse(raw, default_region)`; `normalized = format_number(n, PhoneNumberFormat.E164)`.
  - **Store the E.164 key regardless of `is_valid_number`** — gating on validity would drop legitimate handles (e.g. `555…` test/MVNO ranges parse `possible=True, valid=False`). Use `is_possible_number()` only as a soft confidence flag.
  - **`default_region` comes from the user's macOS locale**, not hardcoded `"US"` — a bare foreign national number parsed with the wrong region silently mis-canonicalizes (`020 8366 1177` + US → `+102083661177`, no exception). Config: `settings.contacts_default_region`, seeded from the OS region at first run, overridable in Settings.
  - **Short codes** (`611`, `911`): detect via `shortnumberinfo.is_valid_short_number`; key as `short:<digits>`, never merged across contacts.
  - `NumberParseException` → if the raw contains `@`, route to `canon_email`; else keep a digits-only last-resort key (storable, flagged low-confidence).
- `canon_email(raw) -> str`: `unicodedata.normalize('NFC', raw).strip().lower()`. **No Gmail dot/`+tag` folding** — that is a gmail.com-only rule and applying it to iCloud/custom domains causes false merges. (If we ever want it, gate strictly on `domain in {gmail.com, googlemail.com}`.)
- `canon_handle(raw, default_region)`: dispatch — `@` → email path, else phone path. This is exactly what `resolve_handle` calls in Slice 2.

### 4.4 Contact photos — in scope
Real photos, with an **initials avatar fallback** whenever a contact has none (or extraction fails). Verified extraction recipe:
- Read `ZABCDRECORD.ZTHUMBNAILIMAGEDATA` (BLOB). **First byte is a storage-type tag**: `0x01` = embedded JPEG (`blob[1:]`); `0x02` = external reference (`blob[1:].rstrip(b"\x00").decode("ascii")` = filename under `<dir>/.AddressBook-v22_SUPPORT/_EXTERNAL_DATA/<name>`). Any other first byte → treat as no-photo, don't crash.
- Images are JFIF/JPEG (validate marker at bytes 6–10); write to app storage (under the app-support dir) as `<person_id>.jpg`, set `photo_path` + `has_photo=true`, serve `image/jpeg` via `GET /api/people/{id}/photo`.
- This is **reverse-engineered, undocumented CoreData**, so every step **degrades gracefully to the initials fallback** on any surprise (unknown first byte, non-JFIF, missing external file, `-wal` staleness). A photo failure never fails the contact's import. Extraction is always attempted; there is no feature flag.

### 4.5 Store methods (`backend/app/store.py`)
Templates: `_email_row` (`store.py:1474`), `upsert_email` (`store.py:1498`), `_email_dict` (`store.py:483`).
- `_PERSON_FIELDS` tuple near `store.py:180`.
- `_person_row(s, source, source_id)` — lookup by `(owner, source, source_id)`.
- `upsert_person(person, *, sync=False)` — get-or-create by source key. **Only sync-owned fields are written from a sync** (`display_name`, names, `phones`, `emails`, `photo_path`, `has_photo`, sync-owned `meta` keys). CRM-native fields (`relationship`, `relationship_strength`, `notes`, `last_contacted_at`, `pinned`) are **never touched by sync**, and `source='manual'` rows are never touched by the Contacts sync at all. (Mirror the "only overwrite when provided" guard at `store.py:1525`.)
- `_person_dict(row)` — API dict; datetimes via `aware_utc(...)`.
- `list_people(...)`, `get_person(id)`, `create_person(...)`, `update_person(id, ...)`, `delete_person(id)` (manual CRUD).
- **`resolve_handle(handle) -> list[dict]`** — `canon_handle`, then return **every** Person carrying that normalized handle (owner-scoped); empty list if none, **ordered most-recently-contacted first, then most-recently-synced**, so a caller wanting just one takes `[0]`. Returning the full set handles **shared handles** correctly (a family landline, spouses on one email): Slice 2 attributes a message to the single match, or disambiguates ("Sue or Bob") when there are several. This is the seam Slice 2 consumes. Implementation: **default is a small `PersonHandle` index table** — `(owner, normalized, person_id, kind, possible)`, rewritten on every `upsert_person`, removed on hard `delete_person` but **kept on soft-delete** (so old messages still resolve to a since-removed contact), making resolve a trivial indexed equality lookup returning N rows. The alternative is a JSONB containment query over `phones`/`emails` + a GIN index; both satisfy the identical interface and tests, so the choice is a local perf call finalized against the live PG at build time. The **interface (list return) is fixed here** — Slice 2 is written against it.

### 4.6 Contacts sync engine — new (`backend/app/contacts_sync.py`)
Clone of `email_sync.py`, minus token handling (no OAuth).
- `run_loop()` gated by `settings.contacts_sync_enabled` + `settings.contacts_sync_seconds` (default **slow**, e.g. 6h — Contacts rarely change), started from the `main.py` lifespan.
- `tick(now)` — never crashes: probe FDA (§5); if denied, `set_connector_status('macos_contacts','needs_access')` and return 0. Else read all stores, `upsert_person(..., sync=True)` each, record `last_sync_at`.
- `trigger()` → `asyncio.to_thread(tick)`, awaited by `POST /api/people/sync`.
- `configure(fake)` test seam.

### 4.6a One-way import semantics & field ownership
The import is **one-way: macOS Contacts → ScuffedOS. We never write to the AddressBook DB** (opened read-only + immutable). Three consequences:
- **Field ownership.** Each `Person` field has exactly one owner. *Sync-owned* fields (`display_name`, names, `organization`, `phones`, `emails`, `photo_path`) are owned by macOS Contacts — re-synced every pass, and shown **read-only** in the ScuffedOS UI for `source='macos_contacts'` people (editing them there would only be overwritten next sync). *CRM-native* fields (`relationship`, `relationship_strength`, `notes`, `pinned`, `last_contacted_at`) are owned by ScuffedOS — freely editable, and **never touched by sync**. `source='manual'` people are fully editable and never touched by the Contacts sync at all.
- **Deletion reconciliation (soft).** When a contact disappears from *all* AddressBook stores, its synced `Person` is **flagged stale** (`meta.removed_from_source_at = <ts>`), **not** hard-deleted — so any CRM-native data (notes, relationship) and later message history is preserved. Stale people drop out of the default People list behind a "no longer in Contacts" filter that offers restore/delete. A hard purge is always an explicit user action, never automatic.
- **Why one-way:** writing back requires undocumented CoreData writes that can corrupt the store and fight Contacts.app/iCloud sync, needs more than FDA, and buys nothing for the messaging goal. Out of scope (§1).

### 4.7 Router + schemas — new (`backend/app/routers/people.py`, `schemas.py`)
- `GET /api/people` (list; `?q=` search, sort by name/last_contacted). `GET /api/people/{id}`. `POST /api/people` (manual create). `PATCH /api/people/{id}` (edit incl. CRM fields). `DELETE /api/people/{id}`. `POST /api/people/sync` (trigger Contacts import). `GET /api/people/{id}/photo` (if photos enabled).
- Pydantic `PersonCreate` / `PersonUpdate` / `PersonOut` in `schemas.py`.
- Register `app.include_router(people.router)` in `main.py` (near `:146`).

### 4.8 Connector catalog + Settings card (`routers/connectors.py`, `schemas.py`, frontend)
- New connector entry `macos_contacts` in `_CATALOG` (`connectors.py:24`) with **`auth_kind: "local"`** (a new kind alongside `oauth`/`token`/`link`).
- `_configured()` for it = an **FDA probe succeeds** (not a stored secret). `ConnectorInfo` schema literal (`schemas.py:431`) gains `auth_kind="local"` and an `access: 'granted' | 'denied' | 'unknown'` field + `last_sync_at`.
- Frontend `ConnectorsPanel.jsx` gets a **`local` branch**: the card shows access state + **"Grant Full Disk Access"** (opens the settings deep link, §5) + **"Sync now"** (`POST /api/people/sync`), instead of an OAuth button.

### 4.9 Frontend (`CRMScreen.jsx`, `lib/api.js`)
- Replace the three hardcoded arrays with `api.listPeople()` on mount.
- Render name, phones, emails, relationship + strength meter (existing UI concepts), photo-or-initials avatar. Add manual add/edit/delete.
- Empty state via `ConnectorEmptyState` → "Connect macOS Contacts" (routes to Settings › Connectors).
- `api.js` gains `listPeople` / `getPerson` / `createPerson` / `updatePerson` / `deletePerson` / `syncContacts` (template = the task methods at `api.js:114`).

### 4.10 Migration (`backend/alembic/versions/0010_people.py`)
`down_revision="0009"` (current head). Creates the `people` table (§4.1) + the `person_handle` index table (§4.5). Migration test in `tests/test_migrations.py`.

---

## 5. Full Disk Access flow (the reusable piece)

Confirmed by adversarial verification (CONFIRMED): a **signed, in-bundle Python sidecar spawned by the Tauri app via `tauri_plugin_shell` inherits the app's FDA grant**, because TCC evaluates the *responsible process* and a plain `posix_spawn` child (no `responsibility_spawnattrs_setdisclaim`) stays attributed to `ScuffedOS.app`. Design constraints that keep this true:

- **Keep the sidecar in-bundle, same Team ID.** Never move it to `/Library/PrivilegedHelperTools` and never launch it as a separate `launchd` agent/daemon — either severs the responsible-process link (this is what macOS 11.4 broke for out-of-bundle helpers).
- **No App Sandbox** (`com.apple.security.app-sandbox` must stay off — FDA is incompatible with the sandbox). `com.apple.security.inherit` is sandbox-only and irrelevant; omit it. There is **no entitlement that grants FDA** — it is purely the user's TCC toggle on the parent app. Hardened-runtime entitlements only govern loading the embedded CPython/`.so`s; the repo already re-signs every nested Mach-O (commit `3d5f917`).
- **Detection = attempt an actual read, catch `PermissionError` errno 1 (EPERM / "Operation not permitted").** Do **not** rely on `os.access()` (POSIX layer can report True while the read is EPERM), and don't let `sqlite3.connect()` swallow it into an opaque `OperationalError` — probe the raw file with `open(path,'rb')` first, branch: `EPERM` → not granted (show grant UI); `ENOENT` (2) → feature/file absent, not a permission problem.
- **Grant UX:** detect EPERM → explainer card → open `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles` (fallback `?Privacy`) via the already-registered Tauri **opener** plugin → user drags/【+】-adds ScuffedOS.app and toggles it on.
- **Relaunch after grant.** A running process does **not** pick up newly-granted FDA — the app must relaunch the sidecar (ideally offer an app relaunch) after the user toggles it. The connect flow polls `GET /api/connectors` (like the existing OAuth connect) and, on continued `denied`, prompts a relaunch.
- **Dev-mode caveat (test-plan item, not a shippable path):** in `tauri dev` the responsible process is the unsigned dev binary, which has no stable identity — **FDA cannot be validated in dev**. Acceptance requires testing on the **signed bundle**, verified with `sudo launchctl procinfo <sidecar_pid> | grep -i responsible` showing the `.app` as responsible. Backend logic is unit-tested via the injectable path + a simulated-EPERM fake instead.

---

## 6. Decision record — raw AddressBook DB vs. `Contacts.framework`

`Contacts.framework` (CNContact) is Apple's sanctioned API and would give stable `imageData`/`thumbnailImageData` without schema reverse-engineering. **Rejected as primary** because: (a) it requires calling ObjC from the Python sidecar via **pyobjc** — a heavy native dependency to vendor into the frozen 3.14 bundle; (b) it is gated by a **separate** `kTCCServiceAddressBook` (Contacts) permission prompt — a second TCC surface — whereas raw DB reads use the **same FDA grant we already need for `chat.db`** in Slice 2; (c) it does nothing for iMessage, so it can't be the unified access story. Raw-DB-under-FDA is one grant, no pyobjc, consistent across both slices. Mitigation for the reverse-engineered-schema risk: runtime `Z_ENT` discovery, `PRAGMA table_info` probing before selecting optional columns, and graceful column-missing/first-byte-surprise handling.

---

## 7. Error handling

- **FDA denied** → connector `needs_access`, sync returns 0, no crash, grant UX (§5).
- **Missing / partial store** (`ENOENT`, a source folder with no DB) → skip that store, continue the union.
- **Schema drift on macOS 26** (target is 26.4.1, schema historically stable at v22 but unverifiable on a live protected DB) → `PRAGMA table_info` gate optional columns; a missing expected table is logged and that store skipped, not fatal.
- **Unparseable phone/garbage label** → fallback keys (§4.3), never abort the row.
- **Photo surprise** (non-`0x01/0x02` byte, non-JFIF, missing external file) → `has_photo=false`, continue.
- **`-wal` present / live DB churn** → `immutable=1` tolerates it; a slightly stale read is acceptable for a 6-hour sync.

---

## 8. Privacy

Contacts data (names, phones, emails, photos) persists **only in the app-managed local Postgres**; no network egress in this slice. This is a **new local-data-access surface**, so the canonical privacy policy (`docs/privacy-policy.md`) gains a "macOS Contacts (local, on-device)" disclosure, mirrored via the **`publish-privacy-policy`** skill (gist + corp site). Full Disk Access rationale is documented user-facing in the connect card copy.

---

## 9. Testing strategy

Mirror the Moodle/Email 6–8 file set. No real Mac files touched — everything runs off fixtures + injectable paths.

- **Fixture AddressBook tree** — a hand-built tiny `.abcddb` SQLite matching the real `ZABCD*` schema (`Z_PRIMARYKEY`, `ZABCDRECORD`, `ZABCDPHONENUMBER`, `ZABCDEMAILADDRESS`), including: a normal contact, a company row (`ZDISPLAYFLAGS` bit0), a NULL-`ZDISPLAYFLAGS` row, a `_$!<...>!$_`-wrapped label, a custom label, a multi-source layout (top-level + one `Sources/<UUID>/`), one `0x01`-embedded photo blob, and one `0x02` external-reference photo (with its `_EXTERNAL_DATA` file).
- `test_contacts_reader.py` — enumeration/union, `Z_ENT` discovery, label unwrap, date conversion, company/NULL handling, injectable path.
- `test_identity_normalize.py` — the phone/email canonicalization table (E.164 variants collapse to one key; validity-agnostic keying; wrong-region trap; short codes; email lowercase-no-dot-folding; parse failures).
- `test_contacts_photos.py` — `0x01`-inline, `0x02`-external, surprise-byte, non-JFIF, and missing-external-file paths — the last three all falling back to initials (`has_photo=false`) without failing the import.
- `test_people_store.py` — upsert-by-source, **don't-clobber-manual** guard, `resolve_handle` hits/misses/**collisions** (shared handle → multiple People, ordered; kept across soft-delete), CRUD.
- `test_contacts_sync.py` — `tick` idempotency, **soft deletion reconciliation** (vanished contact → `removed_from_source_at`, CRM fields preserved), FDA-denied → `needs_access`, `trigger`.
- `test_people_api.py`, `test_people_schema.py` — endpoints + Pydantic.
- `test_connectors*.py` — `macos_contacts` catalog entry, `auth_kind="local"`, `access` field.
- `0010` migration test.
- **FDA responsible-process check** is a manual on-device acceptance step on the signed build (§5), not a unit test.

Report the full suite pass count after each task (repo rule). Baseline ≈ 699 tests.

---

## 10. Slicing within Slice 1 (implementation order, TDD)

1. `identity.py` + `test_identity_normalize.py` (pure, no macOS) — add `phonenumberslite` dep + vendor.
2. `Person` model + `0010` migration + migration test.
3. Store: `_PERSON_FIELDS`/`_person_row`/`upsert_person`/`_person_dict`/CRUD + `PersonHandle` index + `resolve_handle` + `test_people_store.py`.
4. `providers/macos_contacts.py` (incl. photo extraction, §4.4) + fixture tree + `test_contacts_reader.py` + `test_contacts_photos.py`.
5. `contacts_sync.py` (incl. soft deletion reconciliation, §4.6a) + `test_contacts_sync.py` + lifespan wiring + config.
6. `routers/people.py` + schemas + `test_people_api.py`/`test_people_schema.py` + `main.py` include.
7. Connector catalog `macos_contacts` + `auth_kind="local"` + `access` probe + connector tests.
8. Frontend: `CRMScreen.jsx` real data + CRUD; `ConnectorsPanel.jsx` `local` branch; `api.js` methods.
9. Privacy-policy disclosure (publish-privacy-policy skill) + `README`/connector-catalog docs.
10. `GET /api/people/{id}/photo` endpoint + wire real photos (with initials fallback) into the People UI. (Extraction itself lands in step 4.)

**Future work (deferred):** cross-source contact de-dup via `ZLINKID`; two-way editing; contact→message timeline linking (once Slice 2 lands).

---

## 11. The broader messaging arc (context, not this slice)
- **Slice 2 — iMessage read/ingest.** `chat.db` reader (+ `attributedBody` typedstream decoding), `Conversation`/`Message` tables (`0011_messaging`), Messages screen, reusing this slice's FDA grant and `resolve_handle`. Defaults from §2.F apply.
- **Slice 3 — send + notifications.** AppleScript/Shortcuts send (Automation TCC), compose UI, new-message surfacing — under the §2.G no-auto-send gate.
- **Slice 4 — AI triage + drafting.** Thread summaries / importance / draft replies reusing `email_triage.py`/`email_draft.py`, human-approve-before-send.

---

## 12. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| FDA responsible-process chain fails on the real bundle | low (CONFIRMED) | On-device `launchctl procinfo` acceptance check; keep sidecar in-bundle, no launchd, no disclaim |
| macOS 26 schema drift vs. verified 13–15 dumps | low–med | Runtime `Z_ENT` discovery + `PRAGMA table_info` gating; skip-and-log unknown tables |
| Wrong `default_region` silently mis-canonicalizes phones | med | Seed region from OS locale; `is_possible_number` low-confidence flag; same region both sides |
| Photo format reverse-engineered/undocumented | med | Every step degrades to the initials fallback; a photo failure never fails the import |
| `phonenumberslite` metadata ages (offline) | low | Bump the vendored version on app updates; validity is advisory only |
| FDA untestable in `tauri dev` misleads QA | med | Explicit signed-bundle acceptance step; unit-test via injectable path + simulated EPERM |

---

## 13. Doc & housekeeping updates (part of this slice)
- `docs/privacy-policy.md` + publish via skill.
- `README.md` connector list + a short `docs/people.md` (model, sync, FDA).
- Connector catalog / Settings copy for the `local` card.
- `backend/requirements.txt`: add `phonenumberslite`; ensure it's collected by `scripts/vendor-python.sh`.
