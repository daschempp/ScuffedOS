# People (Personal CRM) — Architecture

> Status: **implemented (M10 s1)** · Last updated: 2026-07-13
>
> Part of the [backend overview](backend-overview.md). A personal CRM: contacts
> imported read-only from macOS Contacts, CRM-native relationship metadata
> (relationship, strength, notes, pinned, last-contacted), and manually-added
> people — all behind `/api/people`.

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

## No AI

This slice sends Contacts data to **no AI provider** and to **no third-party
Contacts API**. Contact data is used only to populate the CRM screen and the
`resolve_handle` seam; nothing about a person is included in assistant
context in this slice.

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

- **Assistant → People.** Not wired to assistant context in this slice (see
  "No AI" above); a future slice may add opt-in assistant access to CRM data.
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
