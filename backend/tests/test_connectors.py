"""M9 Slice 1 — GET /api/connectors read-model projection."""
import json
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.providers import macos_contacts
from app.providers.base import NormalizedItem, NormalizedPerson, Tokens
from app.providers.macos_contacts import ContactsSnapshot, SnapshotStatus
from app.store import store


@pytest.fixture(autouse=True)
def _no_ambient_provider_creds(monkeypatch):
    """This dev machine's backend/.env carries REAL Google + WHOOP OAuth
    credentials (used for M4/M5 live-service testing), so the settings
    singleton is non-empty by default here, unlike a clean checkout. Force a
    blank-credentials baseline so the `configured` assertions below are
    deterministic regardless of what happens to be in the local .env."""
    for field in (
        "google_client_id", "google_client_secret",
        "whoop_client_id", "whoop_client_secret",
        "plaid_client_id", "plaid_secret",
    ):
        monkeypatch.setattr(settings, field, "")


def _get(client):
    res = client.get("/api/connectors")
    assert res.status_code == 200
    return {c["name"]: c for c in res.json()}


def test_all_five_present_not_connected_on_empty_db(client):
    # macos_contacts' configured/access/status come from a live platform +
    # FDA probe (see _contacts_connector) — the GLOBAL autouse Contacts seam in
    # conftest.py (macos_contacts.configure(platform="linux")) stubs the
    # platform seam off, so this order/status assertion is deterministic on
    # macOS dev + CI alike, never touching the real AddressBook store during
    # the suite run.
    body = client.get("/api/connectors").json()
    assert [c["name"] for c in body] == [
        "google", "whoop", "moodle", "plaid", "macos_contacts",
    ]
    assert [c["auth_kind"] for c in body] == ["oauth", "oauth", "token", "link", "local"]
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


def test_moodle_always_configured_others_not_without_creds(client):
    body = _get(client)
    assert body["moodle"]["configured"] is True
    assert body["google"]["configured"] is False
    assert body["whoop"]["configured"] is False
    assert body["plaid"]["configured"] is False


def test_configured_flips_when_creds_present(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "gid")
    monkeypatch.setattr(settings, "google_client_secret", "gsecret")
    monkeypatch.setattr(settings, "plaid_client_id", "pid")
    monkeypatch.setattr(settings, "plaid_secret", "psecret")
    body = _get(client)
    assert body["google"]["configured"] is True
    assert body["plaid"]["configured"] is True
    assert body["whoop"]["configured"] is False  # only whoop creds still absent


def test_connected_google_projects_can_write_email(client):
    store.upsert_provider_account(
        "google",
        Tokens(
            access_token="a", refresh_token="r", expires_at=None,
            scopes=(
                "https://www.googleapis.com/auth/gmail.modify "
                "https://www.googleapis.com/auth/gmail.send"
            ),
            provider_user_id="g1",
        ),
    )
    g = _get(client)["google"]
    assert g["status"] == "connected"
    assert g["connected_at"] is not None
    assert g["provider_user_id"] == "g1"
    assert g["can_write_email"] is True


def test_google_needs_reauth_projects_through(client):
    store.upsert_provider_account(
        "google", Tokens(access_token="a", refresh_token="r", expires_at=None,
                          scopes="", provider_user_id="g1"),
    )
    store.set_provider_status("google", "needs_reauth")
    assert _get(client)["google"]["status"] == "needs_reauth"


def test_non_google_can_write_email_is_null_not_false(client):
    store.upsert_provider_account(
        "whoop", Tokens(access_token="a", refresh_token="r", expires_at=None,
                        scopes="read:recovery", provider_user_id="w1"),
    )
    w = _get(client)["whoop"]
    assert w["status"] == "connected"
    assert w["can_write_email"] is None   # store emits False for whoop; projection nulls it


def test_plaid_items_nested_and_status_derived(client):
    store.upsert_finance_item(
        NormalizedItem(item_id="itm1", institution_id="ins_1",
                       institution_name="Chase", products=["transactions"]),
        access_token="tok1",
    )
    store.upsert_finance_item(
        NormalizedItem(item_id="itm2", institution_id="ins_2",
                       institution_name="Fidelity", products=["investments"]),
        access_token="tok2",
    )
    p = _get(client)["plaid"]
    assert p["status"] == "connected"
    assert {i["item_id"] for i in p["items"]} == {"itm1", "itm2"}
    assert all(i["status"] == "connected" for i in p["items"])  # 'active' -> 'connected'

    store.set_finance_item_status("itm2", "needs_reauth")
    p2 = _get(client)["plaid"]
    assert p2["status"] == "needs_reauth"
    statuses = {i["item_id"]: i["status"] for i in p2["items"]}
    assert statuses == {"itm1": "connected", "itm2": "needs_reauth"}


def test_no_token_material_in_response(client):
    store.upsert_provider_account(
        "whoop", Tokens(access_token="secret-access", refresh_token="secret-refresh",
                        expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                        scopes="read:recovery", provider_user_id="w1"),
    )
    store.upsert_finance_item(
        NormalizedItem(item_id="itm1", institution_id="ins_1",
                       institution_name="Chase", products=["transactions"]),
        access_token="plaid-secret-token",
    )
    raw = json.dumps(client.get("/api/connectors").json())
    for leak in ("secret-access", "secret-refresh", "plaid-secret-token",
                 "access_token", "refresh_token", "scopes"):
        assert leak not in raw
