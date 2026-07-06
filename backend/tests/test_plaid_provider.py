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


def test_get_holdings_parses_accounts_securities_holdings():
    http = FakePlaidHTTP(responses={"/investments/holdings/get": {
        "accounts": [{"account_id": "brk", "name": "Coinbase", "type": "investment",
                      "subtype": "crypto", "balances": {"current": 3400.0, "iso_currency_code": "USD"}}],
        "securities": [{"security_id": "s1", "name": "Bitcoin", "ticker_symbol": "BTC",
                        "type": "cryptocurrency", "close_price": 60000, "iso_currency_code": "USD",
                        "is_cash_equivalent": False}],
        "holdings": [{"account_id": "brk", "security_id": "s1", "quantity": 0.05,
                      "cost_basis": 2000, "institution_value": 3000, "institution_price": 60000,
                      "iso_currency_code": "USD"}]}})
    p = _provider(http)
    accts, secs, holds = p.get_holdings("tok")
    assert accts[0].source_id == "brk" and accts[0].type == "investment"
    assert secs[0].type == "cryptocurrency" and secs[0].ticker_symbol == "BTC"
    assert holds[0].quantity == Decimal("0.05")
    assert holds[0].institution_value == Decimal("3000") and holds[0].account_id == "brk"


def test_get_link_public_token_returns_none_until_finished():
    # First poll: no sessions yet. Second poll: a finished session with a public_token.
    http = FakePlaidHTTP(responses={"/link/token/get": seq(
        {"link_token": "l", "link_sessions": []},
        {"link_token": "l", "link_sessions": [
            {"results": {"item_add_results": [{"public_token": "pub-xyz"}]}}]})})
    p = _provider(http)
    assert p.get_link_public_token("l") is None
    assert p.get_link_public_token("l") == "pub-xyz"


def test_remove_item_posts_access_token():
    http = FakePlaidHTTP(responses={"/item/remove": {}})
    p = _provider(http)
    p.remove_item("tok")
    url, body = http.posts[0]
    assert url.endswith("/item/remove") and body["access_token"] == "tok"


def test_plaid_registered_in_real_registry():
    from app import providers
    providers.configure("unset")            # real registry
    try:
        p = providers.get("plaid")
        assert p is not None and p.name == "plaid"
    finally:
        providers.configure([])             # restore test isolation
