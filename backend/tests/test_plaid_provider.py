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
    assert body["additional_consented_products"] == ["investments", "liabilities"]
    assert "hosted_link" in body
    assert body["client_id"] == "cid" and body["secret"] == "sek"


def test_create_link_token_investments_requests_investments():
    http = FakePlaidHTTP(responses={"/link/token/create": {"link_token": "l", "hosted_link_url": "u"}})
    p = _provider(http)
    p.create_link_token("investments")
    _, body = http.posts[0]
    assert body["products"] == ["investments"]
    assert "additional_consented_products" not in body


def test_create_link_token_update_mode_omits_products():
    http = FakePlaidHTTP(responses={"/link/token/create": {"link_token": "l", "hosted_link_url": "u"}})
    p = _provider(http)
    p.create_link_token("bank", access_token="acc-tok")
    _, body = http.posts[0]
    assert body["access_token"] == "acc-tok"
    assert "products" not in body
    assert "additional_consented_products" not in body
    assert "hosted_link" in body


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


def test_get_recurring_parses_inflow_and_outflow():
    http = FakePlaidHTTP(responses={"/transactions/recurring/get": {
        "inflow_streams": [{"stream_id": "in1", "account_id": "a1", "description": "Payroll",
                            "merchant_name": "Acme", "frequency": "BIWEEKLY",
                            "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"},
                            "average_amount": {"amount": 2500, "iso_currency_code": "USD"},
                            "last_amount": {"amount": 2500, "iso_currency_code": "USD"},
                            "last_date": "2026-06-15", "predicted_next_date": "2026-06-29",
                            "is_active": True, "status": "MATURE"}],
        "outflow_streams": [{"stream_id": "out1", "account_id": "a1", "description": "Netflix",
                             "merchant_name": "Netflix", "frequency": "MONTHLY",
                             "personal_finance_category": {"primary": "ENTERTAINMENT",
                                                           "detailed": "ENTERTAINMENT_STREAMING"},
                             "average_amount": {"amount": 15.49, "iso_currency_code": "USD"},
                             "last_amount": {"amount": 15.49, "iso_currency_code": "USD"},
                             "last_date": "2026-06-12", "predicted_next_date": "2026-07-12",
                             "is_active": True, "status": "MATURE"}]}})
    p = _provider(http)
    streams = p.get_recurring("tok")
    by_id = {s.source_id: s for s in streams}
    assert by_id["in1"].stream_type == "inflow"
    assert by_id["out1"].stream_type == "outflow"
    assert by_id["out1"].average_amount == Decimal("15.49")
    assert by_id["out1"].category_primary == "ENTERTAINMENT"
    assert by_id["out1"].predicted_next_date.isoformat() == "2026-07-12"
    _, body = http.posts[0]
    assert body["access_token"] == "tok"


def test_get_liabilities_flattens_types():
    http = FakePlaidHTTP(responses={"/liabilities/get": {"liabilities": {
        "credit": [{"account_id": "cc1", "last_statement_balance": 1250.0,
                    "minimum_payment_amount": 35.0, "next_payment_due_date": "2026-07-15",
                    "last_payment_amount": 200.0, "last_payment_date": "2026-06-10",
                    "aprs": [{"apr_percentage": 19.99, "apr_type": "purchase_apr"}]}],
        "mortgage": [{"account_id": "mg1", "next_monthly_payment": 1800.0,
                      "next_payment_due_date": "2026-07-01"}],
        "student": []}}})
    p = _provider(http)
    liabs = {l.account_id: l for l in p.get_liabilities("tok")}
    assert liabs["cc1"].liability_type == "credit"
    assert liabs["cc1"].minimum_payment == Decimal("35")
    assert liabs["cc1"].apr_percentage == Decimal("19.99")
    assert liabs["mg1"].liability_type == "mortgage"


def test_get_liabilities_feature_absent_returns_empty():
    http = FakePlaidHTTP(
        responses={"/liabilities/get": {"error_code": "PRODUCTS_NOT_SUPPORTED",
                                        "error_message": "no liabilities"}},
        status={"/liabilities/get": 400})
    p = _provider(http)
    assert p.get_liabilities("tok") == []


def test_get_liabilities_auth_error_still_raises():
    http = FakePlaidHTTP(
        responses={"/liabilities/get": {"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "reauth"}},
        status={"/liabilities/get": 400})
    p = _provider(http)
    with pytest.raises(PlaidAuthError):
        p.get_liabilities("tok")


def test_plaid_registered_in_real_registry():
    from app import providers
    providers.configure("unset")            # real registry
    try:
        p = providers.get("plaid")
        assert p is not None and p.name == "plaid"
    finally:
        providers.configure([])             # restore test isolation


def test_get_investment_transactions_pages_and_parses():
    from datetime import date
    page1 = {"accounts": [{"account_id": "brk", "name": "Coinbase", "type": "investment",
                           "subtype": "crypto", "balances": {"current": 3000.0, "iso_currency_code": "USD"}}],
             "securities": [{"security_id": "s1", "name": "Bitcoin", "ticker_symbol": "BTC",
                             "type": "cryptocurrency", "iso_currency_code": "USD"}],
             "investment_transactions": [{"investment_transaction_id": "it1", "account_id": "brk",
                                          "security_id": "s1", "date": "2026-06-10", "name": "BUY BTC",
                                          "quantity": 0.01, "amount": 600.0, "price": 60000.0,
                                          "fees": 1.5, "type": "buy", "subtype": "buy",
                                          "iso_currency_code": "USD"}],
             "total_investment_transactions": 2}
    page2 = {"accounts": [], "securities": [],
             "investment_transactions": [{"investment_transaction_id": "it2", "account_id": "brk",
                                          "security_id": "s1", "date": "2026-06-11", "name": "SELL BTC",
                                          "quantity": -0.005, "amount": -300.0, "price": 60000.0,
                                          "type": "sell", "subtype": "sell", "iso_currency_code": "USD"}],
             "total_investment_transactions": 2}
    http = FakePlaidHTTP(responses={"/investments/transactions/get": seq(page1, page2)})
    p = _provider(http)
    accts, secs, txns = p.get_investment_transactions("tok", date(2026, 6, 1), date(2026, 6, 30))
    ids = {t.source_id for t in txns}
    assert ids == {"it1", "it2"}
    it1 = next(t for t in txns if t.source_id == "it1")
    assert it1.type == "buy" and it1.quantity == Decimal("0.01") and it1.amount == Decimal("600")
    assert secs[0].ticker_symbol == "BTC" and accts[0].source_id == "brk"
    _, body = http.posts[0]
    assert body["start_date"] == "2026-06-01" and body["end_date"] == "2026-06-30"
    assert body["options"]["offset"] == 0
