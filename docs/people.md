# People (Personal CRM) — Architecture

> Status: **implemented (M10 s1, plus the assistant People tools)** · Last updated: 2026-08-19
>
> Part of the [backend overview](backend-overview.md). A personal CRM: contacts
> imported read-only from macOS Contacts, CRM-native relationship metadata
> (relationship, strength, notes, pinned, last-contacted), and manually-added
> people — all behind `/api/people` and the assistant's People tools.

## Responsibility

Own the user's contacts and relationship metadata. Contacts can be imported
one-way from the local macOS Contacts (AddressBook) database, or added
manually. Sync owns identity fields (name, phones, emails, org/title); the CRM
layer owns relationship fields (`relationship`, `relationship_strength`,
`notes`, `pinned`, `last_contacted_at`) which are never touched by sync.

## Model

- **`people`** — one row per contact. Identity fields (`display_name`,
  `first_name`, `last_name`, `nickname`, `organization`, `job_title`); `phones`
  and `emails` as `[{value, label, normalized}]`; CRM-native `relationship`,
  `relationship_strength` (1–5), `notes`, `pinned`, `last_contacted_at`;
  `source` (`macos_contacts` or `manual`); `removed_from_source_at` (soft
  delete, set when a previously-imported contact disappears from a complete
  snapshot); `photo_key` (opaque relative pointer into the photo store, see
  below). Keyed `(owner, source, source_id)` — `source_id` is a namespaced,
  hashed identifier (`sha1(store_id:zuniqueid…)`), never a raw AddressBook
  primary key.
- **`person_handle`** — a normalized handle index (phone/email → person),
  used by `resolve_handle` for the iMessage slice. A handle can point at more
  than one person (shared numbers/emails); resurrected rows keep their handle
  history.
- **`contacts_sync_state`** — one consent/status row per owner: `enabled`
  (app consent, defaults `False`); the persisted `status` (`disabled` /
  `ready` / `access_denied` / `stale` / `error`); the persisted `access`
  (Full Disk Access read state, tracked **separately** from `status`:
  `granted` / `denied` / `unknown`); `normalization_region` (persisted at
  `enable` time); `last_sync_at`; `last_error`. Distinct from both: `POST
  /api/people/sync` returns an **ephemeral**, non-persisted `SyncResult.status`
  (`ok` / `empty` / `access_denied` / `unsupported` / `partial` / `error` /
  `disabled`) describing the outcome of that one sync attempt only.

## Persistence

Structured contact fields are written to **the configured PostgreSQL
database**, which may run **locally (loopback)** or on a **remote/self-hosted
server** — the same database every other ScuffedOS domain uses (see
[data-store.md](data-store.md)). When the database is remote, contact data
(names, phone numbers, email addresses, organization/title) travels over the
network to that server; a non-loopback DSN is **required to use TLS**
(`sslmode=require` or stronger — enforced in `app/db.py`, which rejects a
non-loopback PostgreSQL DSN lacking it). This slice targets a **single backend
host per database**.

Extracted **photos are never stored in PostgreSQL and never in the repo** —
they live as files on the **backend host's filesystem**, under
`app_support_dir/contact_photos` (`contacts_photos_dir`, resolved under
`app_support_dir`). Photos are written atomically (`os.replace`) under a
hashed, opaque `photo_key` (`sha256(store_id:source_id).<ext>`) and served via
`GET /api/people/{id}/photo`, which containment-checks the resolved path
before returning it (guards against a malicious/symlinked key escaping the
photo root) and detects the image media type rather than trusting the
extension. A failure to extract or write a photo never aborts the rest of a
sync pass; superseded photo files are cleaned up on re-sync, forget, and
delete.

## One-way, read-only import

The macOS AddressBook SQLite store(s) are opened **read-only** (`mode=ro` +
`PRAGMA query_only=ON`, inside a bounded read transaction with a
`busy_timeout`) and are **never written back to**. Sync writes only the
sync-owned identity fields listed above; CRM-native fields are
ScuffedOS-owned and are never touched by `apply_contacts_snapshot`. The
reader resolves the `ABCDContact` entity dynamically via `Z_PRIMARYKEY` at
runtime (never a hardcoded `Z_ENT`) and excludes `ABCDGroup`/non-contact
entities, so groups never surface as people.

## Consent + FDA lifecycle

Import is **disabled by default**. App consent (`contacts_sync_state.enabled`)
is tracked **separately** from macOS **Full Disk Access** — both are required
before any AddressBook read is attempted:

- **`POST /api/people/contacts/enable`** — requires the caller to have
  acknowledged the storage disclosure (`ack_storage_disclosure`); rejects the
  request otherwise. On success it stamps `normalization_region` from
  `contacts_default_region` and kicks an immediate sync pass (failures land in
  sync state, never raised to the caller).
- **`POST /api/people/contacts/disconnect`** — stops future syncing but
  **keeps** all previously-imported rows, handles, and photos.
- **`POST /api/people/contacts/forget`** — requires `confirm=true`. Deletes
  all imported rows, their handle-index entries, and their photos. A person
  who has accumulated CRM-native data (relationship, notes, pinned, etc.) is
  **not silently erased** — it is converted to a `source="manual"` tombstone
  so that relationship history survives the forget.
- **Full Disk Access revoked** (in System Settings, outside the app) surfaces
  as sync status **`stale`** on the next attempted read — existing rows are
  **preserved**, not deleted. Access can be restored by re-granting FDA; a
  denied/partial/unsupported read is likewise never treated as "no contacts."

## Complete-snapshot sync

Soft-deletion reconciliation (marking a person `removed_from_source_at`) runs
**only** when a sync pass produces a `COMPLETE_*` snapshot status with **no**
per-record error. A failed, partial, denied, or unsupported read never
soft-deletes anything. An **unreachable PostgreSQL server** during a sync
attempt is treated as a **failed sync** (`status="error"`), never as an empty
contact list — the distinction matters because an empty list would otherwise
look like "the user deleted all their contacts" and trigger reconciliation.
The apply step is a single transaction (rolls back atomically on a mid-apply
DB error) guarded by a process + advisory lock so overlapping sync attempts
serialize rather than race.

## `resolve_handle`

`resolve_handle(handle) -> list[dict]` canonicalizes the input using the
**persisted** `normalization_region` (not a fresh guess) and returns **every**
person carrying that handle — a shared phone number or email can map to more
than one person — ordered most-recently-contacted, and **includes
soft-deleted** people. This is a seam for the future iMessage slice, not
consumed anywhere in this slice.

## Config

- `contacts_sync_enabled` — persisted consent flag mirror (see
  `contacts_sync_state.enabled`, the source of truth).
- `contacts_sync_seconds` — interval between background sync passes (default
  21600s / 6h).
- `contacts_default_region` — default region for phone-number
  canonicalization at `enable` time (default `US`).
- `contacts_photos_dir` — relative photo-store directory name, resolved under
  `app_support_dir` (default `contact_photos`).
- `app_support_dir` — the backend host's App Support root
  (`~/Library/Application Support/ScuffedOS` by default) under which photos
  and other local backend-host artifacts live.

## Assistant access (no gate)

Contacts still reach **no third-party Contacts API**, and sync itself sends
nothing outward — it writes to the configured database and stops. Contact data
*does* reach **Anthropic**: five People tools live in `app/tools.py`
(`list_people`, `get_person`, `create_person`, `update_person`, `log_contact`),
and because they sit in `TOOLS` they ship in `DEFINITIONS` on **every**
assistant turn. There is **no opt-in gate** — the earlier plan for opt-in
assistant access to CRM data was never built, and enabling the Contacts
connector is the only decision the user makes. A tool only runs when the
user's own request drives the model to call it, so this is request-scoped, not
background upload.

Two serializers bound what crosses the seam:

- **`_compact_person`** — the list row, and the base of every other result:
  `id`, `display_name`, `source`, then `nickname` / `organization` /
  `job_title` / `relationship` when set, `relationship_strength`, `pinned`
  when true, `last_contacted_at`, and `notes` truncated to
  `_PERSON_NOTES_CHARS` (200). **No phones, no emails.**
- **`_person_detail`** — `get_person` and every write result: the compact row
  plus `phones` and `emails` as `{value, label}`, `has_photo`, and `notes`
  re-truncated to `_PERSON_DETAIL_NOTES_CHARS` (1000), which overrides the
  list cap.

Deliberately withheld: photo bytes (`has_photo` is a bare flag; `photo_key`
never leaves the store), the `normalized` twin on each phone/email entry (the
handle index stays local), `source_id`, `first_name`/`last_name`, and the
`removed_from_source_at` / `created_at` / `updated_at` bookkeeping.
`list_people` also returns `total_people` — an unfiltered count — so address-book
size is disclosed even on a one-hit search.

Writes go through the same ownership rule as the API: `_PERSON_CRM_FIELDS`
(`relationship`, `relationship_strength`, `notes`, `pinned`) plus
`last_contacted_at` via `log_contact`. `update_person` refuses the **whole**
call if it touches identity on a non-`manual` row, and there is deliberately no
delete tool. The user-facing disclosure lives in
[privacy-policy.md](privacy-policy.md) §4.

**The seam is not the last hop.** "Request-scoped" bounds when a *tool* runs,
not where the resulting conversation text lands. Every turn also drives
`memory_engine`: `assistant._system_prompt` calls `search(message)` (embeds the
raw user message) and the router fires `capture_turn(message, final_text)` in a
background thread. Mem0 is configured with an **Anthropic** extraction LLM and
an **OpenAI** embedder, so the exchange is embedded by OpenAI, extracted by
Anthropic, and each extracted fact embedded and stored. Two consequences worth
holding onto: contacts do reach a **second provider** (OpenAI) whenever contact
text surfaces in the user's message or the assistant's reply — the "no third-party
Contacts API" claim above is about Contacts APIs, not about providers in
general — and because `search` runs on every turn, a contact-derived memory can
be re-sent to Anthropic on later, unrelated turns. `capture_turn` receives only
the user message and the final assistant text, so raw `_person_detail` payloads
(phones, emails) never enter the memory pipeline directly.

## Source-aware CRUD

- Imported (`source="macos_contacts"`) rows: identity fields
  (`display_name`, `first_name`, `last_name`, `nickname`, `organization`,
  `job_title`, `phones`, `emails`) are **read-only** through the API — a PATCH
  touching any of them on a non-`manual` row is rejected (409); edit them in
  Apple Contacts instead. CRM-native fields (`relationship`,
  `relationship_strength`, `notes`, `pinned`, `last_contacted_at`) are
  editable on any row regardless of source.
- Hard delete (`DELETE /api/people/{id}`) is allowed only for `source="manual"`
  rows; deleting an imported row is rejected (409) — use Disconnect or Forget
  instead, which handle imported rows in bulk (and tombstone CRM-annotated
  ones rather than losing their history).
- `GET /api/people?q=&cursor=` returns `{items, next_cursor}` with a
  deterministic sort, substring search, and cursor pagination.

## Dependencies & interactions

- **Assistant → People.** Wired, ungated: `list_people` / `get_person` read the
  CRM and `create_person` / `update_person` / `log_contact` write its app-native
  fields, on every turn (see "Assistant access (no gate)" above). The opt-in
  gate this doc once anticipated does not exist.
- **People ↔ Email.** Email senders are contacts; a future slice could update
  `last_contacted_at` from sent/received mail. See [email.md](email.md).
- **People → Calendar.** Important dates (birthdays/anniversaries) remain
  deferred; see [calendar.md](calendar.md).
- **People → iMessage (future).** `resolve_handle` exists specifically as the
  handle→person seam for a future iMessage slice.
- **Store.** Persists via the shared data layer — see
  [data-store.md](data-store.md).

## Deferred (not in this slice)

Cross-source dedup via `ZLINKID`; contact → message timeline; two-way editing
back into Apple Contacts; multi-host/shared-database photo storage with a
distributed sync lease; the on-hardware Full-Disk-Access responsible-process
acceptance run (kept as a manual, CI-skipped test — it cannot run in CI or
`tauri dev`).

## Open questions / future work

- Auto-update `relationship_strength`/`last_contacted_at` from Email/Calendar
  activity, or keep manual/import-only?
- Where do important dates live — here or in Calendar?
- Multi-host photo storage once more than one backend host shares a database.
