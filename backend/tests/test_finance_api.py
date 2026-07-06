"""M7 /api/finance/* — connect (Hosted Link), DB-only reads, local budget
writes, disconnect. FakePlaidProvider installed per test; no network."""
from decimal import Decimal

from app import providers
from app.providers.base import (
    NormalizedAccount, NormalizedHolding, NormalizedItem,
    NormalizedSecurity, NormalizedTransaction, TransactionsDelta,
)
from app.store import store


def test_finance_schemas_import():
    from app.schemas import (  # noqa: F401
        AccountsOut, BudgetOut, BudgetReallocate, BudgetsUpdate, FinanceStatus,
        FinanceSummary, HoldingOut, LinkComplete, LinkStart, LinkStartOut,
        NetWorth, TransactionOut,
    )
    assert LinkStart(kind="bank").kind == "bank"


def test_link_start_returns_hosted_url(client):
    from tests.fakes import FakePlaidProvider
    providers.configure([FakePlaidProvider()])
    res = client.post("/api/finance/link/start", json={"kind": "bank"})
    assert res.status_code == 200
    assert res.json()["hosted_link_url"] == "https://plaid/hl"
    assert res.json()["link_token"] == "link-1"


def test_link_complete_stores_item_and_returns_status(client):
    from tests.fakes import FakePlaidProvider
    item = NormalizedItem(item_id="itm1", institution_id="ins_1",
                          institution_name="Chase", products=["transactions"])
    providers.configure([FakePlaidProvider(item=item, accounts=[], delta=TransactionsDelta())])
    res = client.post("/api/finance/link/complete", json={"link_token": "l"})
    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["items"][0]["institution_name"] == "Chase"
    assert "access_token" not in body["items"][0]           # never serialized


def test_link_complete_409_when_not_finished(client):
    from tests.fakes import FakePlaidProvider
    p = FakePlaidProvider()
    p.public_token = None                                   # user hasn't finished on Plaid's page
    providers.configure([p])
    res = client.post("/api/finance/link/complete", json={"link_token": "l"})
    assert res.status_code == 409


def test_status_reflects_linked_items(client):
    from tests.fakes import FakePlaidProvider
    providers.configure([FakePlaidProvider()])
    client.post("/api/finance/link/complete", json={"link_token": "l"})
    res = client.get("/api/finance/status")
    assert res.status_code == 200 and res.json()["connected"] is True


def _seed_synced(client):
    """Link one item + push accounts/txn/holdings through a sync via the fake."""
    from datetime import date
    from tests.fakes import FakePlaidProvider
    acc = NormalizedAccount(source="plaid", source_id="a1", item_id="itm1", name="Checking",
                            official_name=None, mask="1", type="depository", subtype="checking",
                            current_balance=Decimal("4820.50"), available_balance=Decimal("4820.50"),
                            iso_currency="USD")
    txn = NormalizedTransaction(source="plaid", source_id="t1", account_id="a1", item_id="itm1",
                                name="WF", merchant_name="WF", amount=Decimal("64.20"),
                                iso_currency="USD", date=date(2026, 6, 8), authorized_date=None,
                                pending=False, category_primary="FOOD_AND_DRINK",
                                category_detailed="FOOD_AND_DRINK_GROCERIES", payment_channel="in store")
    delta = TransactionsDelta(added=[txn], next_cursor="C1", has_more=False)
    providers.configure([FakePlaidProvider(item=NormalizedItem(
        item_id="itm1", institution_id="ins_1", institution_name="Chase",
        products=["transactions"]), accounts=[acc], delta=delta)])
    client.post("/api/finance/link/complete", json={"link_token": "l"})


def test_summary_accounts_transactions_reads(client):
    _seed_synced(client)
    summ = client.get("/api/finance/summary?month=2026-06").json()
    assert summ["balance"] == 4820.50
    accts = client.get("/api/finance/accounts").json()
    assert accts["accounts"][0]["name"] == "Checking"
    assert any(b["name"] == "Cash" for b in accts["networth"]["buckets"])
    txns = client.get("/api/finance/transactions").json()
    assert txns[0]["source_id"] == "t1" and txns[0]["category"] == "FOOD_AND_DRINK"


def test_holdings_read(client):
    from tests.fakes import FakePlaidProvider
    sec = NormalizedSecurity(source="plaid", source_id="s1", name="Bitcoin", ticker_symbol="BTC",
                             type="cryptocurrency", close_price=Decimal("60000"), iso_currency="USD")
    hold = NormalizedHolding(source="plaid", item_id="itm1", account_id="brk", security_id="s1",
                             quantity=Decimal("0.05"), institution_value=Decimal("3000"), iso_currency="USD")
    acc = NormalizedAccount(source="plaid", source_id="brk", item_id="itm1", name="Coinbase",
                            official_name=None, mask=None, type="investment", subtype="crypto",
                            current_balance=Decimal("3000"), available_balance=None, iso_currency="USD")
    providers.configure([FakePlaidProvider(item=NormalizedItem(
        item_id="itm1", institution_id="ins_1", institution_name="Coinbase", products=["investments"]),
        holdings=([acc], [sec], [hold]))])
    client.post("/api/finance/link/complete", json={"link_token": "l"})
    holds = client.get("/api/finance/holdings").json()
    assert holds[0]["ticker"] == "BTC" and holds[0]["is_crypto"] is True and holds[0]["value"] == 3000.0
