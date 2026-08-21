from datetime import datetime, timezone

import pytest

from app.config import settings
from app.models import PersonHandle
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


# ---- list_people: search reaches emails + phones through the handle index ----

def test_list_people_search_finds_email_and_phone_handles():
    # Sam is MANUAL: manual rows must be indexed too, or handle search silently
    # misses everyone the user added by hand.
    store.create_person({
        "display_name": "Sam Ito",
        "phones": [{"value": "(555) 123-4567", "label": "Cell"}],
        "emails": [{"value": "Sam@Example.org", "label": "Work"}],
    })
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Jane Doe",
        emails=[{"value": "jane@example.org"}])]), NOW)

    def names(**kw):
        return {p["display_name"] for p in store.list_people(**kw)["items"]}

    assert names(q="SAM@") == {"Sam Ito"}                      # manual row indexed, case-insensitive
    assert names(q="jane@") == {"Jane Doe"}                    # synced row indexed too
    # The shared DOMAIN identifies nobody and must not return both -- see
    # test_list_people_email_search_ignores_a_shared_domain below.
    assert names(q="example.org") == set()
    assert names(q="+15551234567") == {"Sam Ito"}              # canonical spelling
    assert names(q="555-123") == {"Sam Ito"}                   # user spelling -> digits variant
    assert names(q="(555) 123-4567") == {"Sam Ito"}
    # Too few digits to be a phone search: must not drag in every stored number.
    assert names(q="55") == set()
    assert names(q="Ito") == {"Sam Ito"}                       # name search still works


def test_list_people_search_returns_a_person_once_per_matching_handle():
    store.create_person({"display_name": "Multi Handle",
                         "phones": [{"value": "+15550001111"},
                                    {"value": "+15550001112"},
                                    {"value": "+15550001113"}]})
    page = store.list_people(q="555000111", limit=2)
    assert [p["display_name"] for p in page["items"]] == ["Multi Handle"]
    assert page["next_cursor"] is None                         # one row, not three


def test_list_people_handle_search_hides_soft_deleted_people_unless_asked():
    store.apply_contacts_snapshot(_snap([_np(source_id="A", display_name="Gone",
        phones=[{"value": "+15557770000"}])]), NOW)
    assert [p["display_name"] for p in store.list_people(q="5557770000")["items"]] == ["Gone"]
    store.apply_contacts_snapshot(_snap([], status=SnapshotStatus.COMPLETE_EMPTY), NOW)
    # The handle row survives the soft delete (resolve_handle needs it) -- the
    # search must still hide the tombstoned person.
    assert store.resolve_handle("+15557770000")
    assert store.list_people(q="5557770000")["items"] == []
    assert [p["display_name"] for p in
            store.list_people(q="5557770000", include_removed=True)["items"]] == ["Gone"]


def test_list_people_handle_search_pages_without_skipping_or_repeating():
    for name in ["Ana", "Ben", "Cyd", "Dot", "Eve"]:
        store.create_person({"display_name": name,
                             "emails": [{"value": f"team.{name.lower()}@shared.test"}]})
    store.create_person({"display_name": "Zed", "emails": [{"value": "zed@other.test"}]})
    seen, cursor = [], None
    for _ in range(5):                                          # bounded: a repeat loop must fail
        page = store.list_people(q="team.", limit=2, cursor=cursor)
        seen.extend(p["display_name"] for p in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert seen == ["Ana", "Ben", "Cyd", "Dot", "Eve"]


def test_list_people_email_search_ignores_a_shared_domain():
    """A domain is shared by design, so matching it as a substring dumped the whole
    address book -- worse than the pre-handle-search behaviour, which found nobody."""
    for name in ["Ada", "Ben", "Rhea", "Sun", "Tia"]:
        store.create_person({"display_name": name,
                             "emails": [{"value": f"{name.lower()}@gmail.com"}]})

    def names(q):
        return {p["display_name"] for p in store.list_people(q=q)["items"]}

    for fragment in ("co", "com", "gmail", "gmail.com", "@gmail.com", "ail.com"):
        assert names(fragment) == set(), fragment
    assert names("ada") == {"Ada"}                  # the local part still identifies its owner
    assert names("ada@gmail.com") == {"Ada"}        # ...and so does the pasted full address


def test_list_people_email_search_matches_from_the_start_of_the_address():
    # Display name deliberately shares no substring with the address: these
    # assertions must be answered by the handle index, not the name clauses.
    store.create_person({"display_name": "Priya Raman",
                         "emails": [{"value": "PR.raman42@work.test"}]})

    def names(q):
        return {p["display_name"] for p in store.list_people(q=q)["items"]}

    assert names("pr.raman42@work.test") == {"Priya Raman"}   # pasted address
    assert names("PR.Raman42") == {"Priya Raman"}             # whole local part, case-insensitive
    assert names("pr.ram") == {"Priya Raman"}                 # prefix of the local part
    # Accepted cost of the prefix rule: the tail of an address is not a search
    # key. "raman42" reaches this person only through her name fields.
    assert names("raman42") == set()


def test_list_people_handle_search_is_owner_scoped():
    mine = store.create_person({"display_name": "Mine",
                                "emails": [{"value": "shared@work.test"}]})
    original = settings.owner
    try:
        settings.owner = "someone-else"
        store.create_person({"display_name": "Theirs",
                             "emails": [{"value": "shared@work.test"}]})
    finally:
        settings.owner = original
    assert [p["display_name"] for p in store.list_people(q="shared@work.test")["items"]] == ["Mine"]
    # A handle row owned by someone else must not pull one of my people in.
    with store._session() as s, s.begin():
        s.add(PersonHandle(owner="someone-else", person_id=mine["id"],
                           kind="phone", value="+15558889999"))
    assert store.list_people(q="5558889999")["items"] == []


def test_list_people_search_treats_like_wildcards_as_literal_text():
    """`%` and `_` are user text, not pattern syntax. Unescaped they reinstated the
    exact substring search the prefix rule removed: "%com" became "%com%"."""
    for name in ["Ada", "Ben"]:
        store.create_person({"display_name": name,
                             "emails": [{"value": f"{name.lower()}@gmail.com"}]})
    store.create_person({"display_name": "Nadia", "organization": "Comcast"})
    store.create_person({"display_name": "Percy Dale",
                         "emails": [{"value": "%da@work.test"}]})

    def names(q):
        return {p["display_name"] for p in store.list_people(q=q)["items"]}

    assert names("%com") == set()           # not a wildcard: no handle/field holds "%com"
    assert names("_da") == set()            # "_" must not stand in for the "a" of "ada@"
    assert names("%da") == {"Percy Dale"}   # ...and a literal "%" still finds the address with one
    assert names("com") == {"Nadia"}        # escaping did not break ordinary substring search


def test_list_people_email_search_ignores_short_code_handles():
    """Short codes are stored as the literal "short:<n>" (app.identity), so an
    unscoped letters clause made "sh" return every contact carrying one."""
    store.create_person({"display_name": "Sharon Vega",
                         "emails": [{"value": "sharon@work.test"}]})
    store.create_person({"display_name": "Text Line", "phones": [{"value": "741741"}]})

    def names(q):
        return {p["display_name"] for p in store.list_people(q=q)["items"]}

    assert names("sh") == {"Sharon Vega"}     # an email prefix, never the "short:" prefix
    assert names("short:") == set()
    assert names("741741") == {"Text Line"}   # digits still reach the short code
