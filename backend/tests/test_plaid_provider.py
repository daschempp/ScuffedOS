"""M7 — the real PlaidProvider driven by FakePlaidHTTP (no network). Covers
link-token per kind, public-token exchange, item/institution resolution,
accounts, /transactions/sync paging, holdings, and error→PlaidAuthError."""
from decimal import Decimal

import pytest

from app.config import settings
from app.providers.base import NormalizedItem
from app.providers.plaid import PlaidAuthError, PlaidError, PlaidProvider
from tests.fakes import FakePlaidHTTP, seq


def _provider(http):
    p = PlaidProvider()
    p.configure(fake_http=http)
    return p


def test_create_link_token_bank_requests_transactions(monkeypatch):
    monkeypatch.setattr(settings, "plaid_client_id", "cid")
    monkeypatch.setattr(settings, "plaid_secret", "sek")
    http = FakePlaidHTTP(responses={"/link/token/create": {
        "link_token": "link-1", "hosted_link_url": "https://plaid/hl", "expiration": "2026-07-05"}})
    p = _provider(http)
    out = p.create_link_token("bank")
    assert out["link_token"] == "link-1"
    assert out["hosted_link_url"] == "https://plaid/hl"
    url, body = http.posts[0]
    assert url.endswith("/link/token/create")
    assert body["products"] == ["transactions"]
    assert body["additional_consented_products"] == ["investments"]
    assert "hosted_link" in body
    assert body["client_id"] == "cid" and body["secret"] == "sek"


def test_create_link_token_investments_requests_investments():
    http = FakePlaidHTTP(responses={"/link/token/create": {"link_token": "l", "hosted_link_url": "u"}})
    p = _provider(http)
    p.create_link_token("investments")
    _, body = http.posts[0]
    assert body["products"] == ["investments"]
    assert "additional_consented_products" not in body


def test_exchange_public_token():
    http = FakePlaidHTTP(responses={"/item/public_token/exchange": {
        "access_token": "acc-tok", "item_id": "itm1"}})
    p = _provider(http)
    assert p.exchange_public_token("pub-1") == ("acc-tok", "itm1")


def test_get_item_resolves_institution_name_and_products():
    http = FakePlaidHTTP(responses={
        "/item/get": {"item": {"item_id": "itm1", "institution_id": "ins_1",
                               "billed_products": ["transactions"],
                               "available_products": ["investments"]}},
        "/institutions/get_by_id": {"institution": {"name": "Chase"}},
    })
    p = _provider(http)
    item = p.get_item("acc-tok")
    assert isinstance(item, NormalizedItem)
    assert item.institution_name == "Chase"
    assert set(item.products) == {"transactions", "investments"}


def test_call_maps_auth_error_code():
    http = FakePlaidHTTP(
        responses={"/item/get": {"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "reauth"}},
        status={"/item/get": 400})
    p = _provider(http)
    with pytest.raises(PlaidAuthError):
        p.get_item("acc-tok")


def test_call_maps_non_auth_error_to_plaiderror():
    http = FakePlaidHTTP(
        responses={"/item/get": {"error_code": "RATE_LIMIT_EXCEEDED", "error_message": "slow"}},
        status={"/item/get": 429})
    p = _provider(http)
    with pytest.raises(PlaidError):
        p.get_item("acc-tok")


def test_get_accounts_parses_balances():
    http = FakePlaidHTTP(responses={"/accounts/get": {
        "item": {"item_id": "itm1"},
        "accounts": [{"account_id": "a1", "name": "Checking", "official_name": "Plaid Checking",
                      "mask": "1234", "type": "depository", "subtype": "checking",
                      "balances": {"current": 100.5, "available": 90.0, "iso_currency_code": "USD"}}]}})
    p = _provider(http)
    accs = p.get_accounts("tok")
    assert len(accs) == 1
    assert accs[0].current_balance == Decimal("100.5")
    assert accs[0].type == "depository" and accs[0].item_id == "itm1"


def test_sync_transactions_one_page():
    http = FakePlaidHTTP(responses={"/transactions/sync": {
        "added": [{"transaction_id": "t1", "account_id": "a1", "name": "WF",
                   "merchant_name": "Whole Foods", "amount": 64.2, "iso_currency_code": "USD",
                   "date": "2026-06-08", "authorized_date": "2026-06-07", "pending": False,
                   "personal_finance_category": {"primary": "FOOD_AND_DRINK",
                                                 "detailed": "FOOD_AND_DRINK_GROCERIES"},
                   "payment_channel": "in store"}],
        "modified": [], "removed": [{"transaction_id": "t9"}],
        "next_cursor": "CUR2", "has_more": True}})
    p = _provider(http)
    delta = p.sync_transactions("tok", None)
    assert delta.added[0].amount == Decimal("64.2")
    assert delta.added[0].category_primary == "FOOD_AND_DRINK"
    assert delta.removed == ["t9"]
    assert delta.next_cursor == "CUR2" and delta.has_more is True
    # cursor omitted on the first call, present on a subsequent one.
    _, body = http.posts[0]
    assert "cursor" not in body
    p.sync_transactions("tok", "CUR2")
    _, body2 = http.posts[1]
    assert body2["cursor"] == "CUR2"
