"""M9 Slice 1 — GET /api/connectors read-model projection."""
import json
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.providers import macos_contacts
from app.providers.base import NormalizedItem, Tokens
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


@pytest.fixture(autouse=True)
def _no_real_contacts(monkeypatch):
    """Every test in this file calls GET /api/connectors, which invokes
    _contacts_connector() unconditionally. On a macOS dev host,
    macos_contacts.is_supported() is True and the real AddressBook store
    exists, so without this seam probe_access() would perform a REAL
    open+read of the developer's live, TCC-protected Contacts DB as an
    unintended side effect of these tests — exactly the privacy/hygiene
    property the connector's test seam exists to guarantee. Force the
    platform seam off file-wide so is_supported() is False, configured
    resolves to False, and probe_access() is never reached."""
    monkeypatch.setattr(macos_contacts, "_is_darwin", lambda: False)


def _get(client):
    res = client.get("/api/connectors")
    assert res.status_code == 200
    return {c["name"]: c for c in res.json()}


def test_all_five_present_not_connected_on_empty_db(client):
    # macos_contacts' configured/access/status come from a live platform +
    # FDA probe (see _contacts_connector) — the file-scoped `_no_real_contacts`
    # autouse fixture above stubs the platform seam off, so this order/status
    # assertion is deterministic on macOS dev + CI alike, never touching the
    # real AddressBook store during the suite run.
    body = client.get("/api/connectors").json()
    assert [c["name"] for c in body] == [
        "google", "whoop", "moodle", "plaid", "macos_contacts",
    ]
    assert [c["auth_kind"] for c in body] == ["oauth", "oauth", "token", "link", "local"]
    for c in body:
        assert c["status"] == "not_connected"
        assert c["connected_at"] is None
        assert c["items"] == []


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
