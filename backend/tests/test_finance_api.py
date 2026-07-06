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
