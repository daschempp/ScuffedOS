"""M10 assistant People tools: browse/search the CRM, read one person, add
someone manually, edit the CRM-owned fields, and stamp last contact.

The load-bearing rules here are (a) `q` must reach the store's server-side
search — a Python filter over the first page would silently hide anyone past
it — and (b) the tool must not become a back door around the router's
"imported identity is read-only" rule.
"""
import json

from app import tools
from app.config import settings
from app.models import Person
from app.schemas import ChatAction
from app.store import store


def _insert_imported(**over) -> int:
    """A synced (source='macos_contacts') row — identity on these is sync-owned."""
    fields = dict(owner=settings.owner, source="macos_contacts", source_id="src-1",
                  display_name="Imported Person", phones=[], emails=[], meta={})
    fields.update(over)
    with store._session() as s, s.begin():
        row = Person(**fields)
        s.add(row)
        s.flush()
        return row.id


def _run(name: str, args: dict):
    result, action = tools.execute(name, args)
    return json.loads(result), action


def test_people_tools_are_registered():
    names = {t["name"] for t in tools.TOOLS}
    assert {"list_people", "get_person", "create_person", "update_person",
            "log_contact"} <= names
    # Deleting a contact from chat is destructive-by-accident, and a synced row
    # would resurrect on the next sync anyway — deliberately not exposed.
    assert "delete_person" not in names
    assert names == {d["name"] for d in tools.DEFINITIONS}


def test_list_people_search_hits_the_store_not_the_first_page():
    for name in ("Aaron Ant", "Bea Bee", "Cara Cat", "Dan Dog"):
        store.create_person({"display_name": name})
    store.create_person({"display_name": "Zelda Zimmer", "organization": "Acme"})

    page, _ = _run("list_people", {"limit": 2})
    assert [p["display_name"] for p in page["people"]] == ["Aaron Ant", "Bea Bee"]
    assert page["more"] is True
    assert page["total_people"] == 5

    # Zelda is nowhere near the first page, so only a server-side q can find her.
    found, _ = _run("list_people", {"q": "zelda", "limit": 2})
    assert [p["display_name"] for p in found["people"]] == ["Zelda Zimmer"]
    assert found["more"] is False
    # ...and search covers organization the same way the store's does.
    by_org, _ = _run("list_people", {"q": "acme", "limit": 2})
    assert [p["display_name"] for p in by_org["people"]] == ["Zelda Zimmer"]


def test_list_people_q_description_matches_the_handle_search_rules():
    """The q description is the model's only map of the search; a drift here
    makes it drop q on an email/phone question and answer from page one."""
    from app import store as store_module

    pid = _run("create_person", {"display_name": "Ada Lovelace",
                                 "emails": ["ada@gmail.com"],
                                 "phones": ["+1 555 555 0134"]})[0]["person"]["id"]

    def ids(q):
        return [p["id"] for p in _run("list_people", {"q": q})[0]["people"]]

    assert ids("ada@gm") == [pid]        # email matches as a prefix...
    assert ids("gmail.com") == []        # ...and never from inside the domain
    assert ids("555-0134") == [pid]      # digits-only q: fragment of the number
    assert ids("55") == []               # under the minimum, not a phone search

    desc = next(d for d in tools.DEFINITIONS
                if d["name"] == "list_people")["input_schema"]["properties"]["q"]["description"]
    lowered = desc.lower()
    assert "email" in lowered and "phone" in lowered
    assert "start" in lowered                       # the email prefix rule
    assert str(store_module._HANDLE_MIN_DIGITS) in desc


def test_list_people_rows_stay_compact():
    store.create_person({"display_name": "Ada Lovelace", "notes": "x" * 900,
                         "phones": [{"value": "+1 555 0100", "label": "mobile"}],
                         "relationship": "Friend", "pinned": True})
    page, action = _run("list_people", {})
    row = page["people"][0]
    assert action is None                       # reads leave no receipt
    assert len(row["notes"]) <= 200
    assert row["relationship"] == "Friend" and row["pinned"] is True
    # No photo plumbing and no phone/email payload in a list row.
    assert not {"photo_key", "has_photo", "phones", "emails"} & row.keys()


def test_get_person_returns_bounded_detail():
    pid = store.create_person({
        "display_name": "Ada Lovelace", "organization": "Analytical Engines",
        "notes": "y" * 4000,
        "phones": [{"value": "+1 555 0100", "label": "mobile"}],
        "emails": [{"value": "ada@example.com", "label": "work"}]})["id"]

    person, action = _run("get_person", {"person_id": pid})
    assert action is None
    assert person["display_name"] == "Ada Lovelace"
    assert person["organization"] == "Analytical Engines"
    assert person["phones"] == [{"value": "+1 555 0100", "label": "mobile"}]
    assert person["emails"] == [{"value": "ada@example.com", "label": "work"}]
    assert len(person["notes"]) <= 1000
    assert "photo_key" not in person


def test_get_person_unknown_id_is_a_clean_error():
    result, action = _run("get_person", {"person_id": 4242})
    assert action is None
    assert "4242" in result["error"]
    assert "Traceback" not in result["error"]


def test_create_person_writes_and_returns_an_action_card():
    result, action = _run("create_person", {
        "display_name": "Grace Hopper", "organization": "USN",
        "relationship": "Mentor", "relationship_strength": 5,
        "phones": ["+1 555 0142"], "emails": ["grace@example.com"],
        "notes": "met at the compiler talk"})

    assert result["person"]["display_name"] == "Grace Hopper"
    assert result["person"]["relationship"] == "Mentor"
    assert ChatAction(**action).screen == "people"
    assert action["title"] and action["meta"]

    stored = store.get_person(result["person"]["id"])
    assert stored["source"] == "manual"
    assert stored["relationship_strength"] == 5
    assert [p["value"] for p in stored["phones"]] == ["+1 555 0142"]
    assert [e["value"] for e in stored["emails"]] == ["grace@example.com"]


def test_create_person_rejects_a_blank_name_cleanly():
    result, action = _run("create_person", {"display_name": "   "})
    assert action is None
    assert "error" in result and "ValueError" not in result["error"]
    assert store.count_people() == 0


def test_update_person_writes_the_crm_owned_fields():
    pid = store.create_person({"display_name": "Ada Lovelace"})["id"]
    result, action = _run("update_person", {
        "person_id": pid, "relationship": "Friend", "relationship_strength": 4,
        "notes": "loves punch cards", "pinned": True})

    assert ChatAction(**action).screen == "people"
    assert result["person"]["relationship"] == "Friend"
    stored = store.get_person(pid)
    assert (stored["relationship"], stored["relationship_strength"]) == ("Friend", 4)
    assert stored["notes"] == "loves punch cards" and stored["pinned"] is True


def test_update_person_refuses_identity_edits_on_a_synced_row():
    pid = _insert_imported(display_name="Mom", organization="Home")
    result, action = _run("update_person", {
        "person_id": pid, "display_name": "Hacked", "notes": "should not land"})

    assert action is None
    assert "Apple Contacts" in result["error"]
    stored = store.get_person(pid)
    assert stored["display_name"] == "Mom"
    assert stored["notes"] is None          # the whole patch is refused, not half of it

    # CRM-owned fields on the same synced row are still writable.
    ok, ok_action = _run("update_person", {"person_id": pid, "relationship": "Family"})
    assert ok["person"]["relationship"] == "Family"
    assert ChatAction(**ok_action).screen == "people"
    assert store.get_person(pid)["display_name"] == "Mom"


def test_update_person_never_writes_identity_even_on_a_manual_row():
    # Tool args skip the API's Pydantic layer, so the executor's allowlist — not
    # the input schema — is what keeps identity out of the patch.
    pid = store.create_person({"display_name": "Ada Lovelace"})["id"]
    result, _ = _run("update_person", {
        "person_id": pid, "display_name": "Hacked", "emails": ["x@y.com"],
        "pinned": True})

    assert result["person"]["pinned"] is True
    stored = store.get_person(pid)
    assert stored["display_name"] == "Ada Lovelace"
    assert stored["emails"] == []


def test_update_person_needs_at_least_one_crm_field():
    pid = store.create_person({"display_name": "Ada Lovelace"})["id"]
    result, action = _run("update_person", {"person_id": pid})
    assert action is None
    assert "relationship" in result["error"]


def test_update_person_unknown_id_is_a_clean_error():
    result, action = _run("update_person", {"person_id": 4242, "pinned": True})
    assert action is None
    assert "4242" in result["error"]


def test_log_contact_stamps_last_contacted_at_on_a_synced_row():
    pid = _insert_imported(display_name="Mom")
    result, action = _run("log_contact", {"person_id": pid})

    assert result["person"]["last_contacted_at"]
    assert ChatAction(**action).screen == "people"
    assert "Mom" in action["meta"]
    assert store.get_person(pid)["last_contacted_at"] is not None


def test_log_contact_accepts_an_explicit_time():
    pid = store.create_person({"display_name": "Ada Lovelace"})["id"]
    _run("log_contact", {"person_id": pid, "when": "2026-06-12T14:00"})
    stamped = store.get_person(pid)["last_contacted_at"]
    assert stamped is not None and stamped.year == 2026 and stamped.month == 6


def test_log_contact_unknown_id_is_a_clean_error():
    result, action = _run("log_contact", {"person_id": 4242})
    assert action is None
    assert "4242" in result["error"]
