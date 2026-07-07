"""M7 finance_sync — per-Item pull; transactions branch, investments branch,
paging, and AuthError -> needs_reauth. No network (FakePlaidProvider)."""
from decimal import Decimal

from app import finance_sync, providers
from app.providers.base import (
    NormalizedAccount, NormalizedHolding, NormalizedItem,
    NormalizedSecurity, NormalizedTransaction, TransactionsDelta,
)
from app.store import store


def _seed_item(item_id="itm1", products=("transactions",)):
    store.upsert_finance_item(
        NormalizedItem(item_id=item_id, institution_id="ins_1",
                       institution_name="Chase", products=list(products)),
        access_token="tok")


def _acct(source_id="a1"):
    return NormalizedAccount(source="plaid", source_id=source_id, item_id="itm1",
                             name="Checking", official_name=None, mask="1", type="depository",
                             subtype="checking", current_balance=Decimal("100"),
                             available_balance=Decimal("100"), iso_currency="USD")


def _txn(source_id="t1"):
    from datetime import date
    return NormalizedTransaction(source="plaid", source_id=source_id, account_id="a1",
                                 item_id="itm1", name="WF", merchant_name="WF",
                                 amount=Decimal("10"), iso_currency="USD", date=date(2026, 6, 8),
                                 authorized_date=None, pending=False,
                                 category_primary="FOOD_AND_DRINK", category_detailed="",
                                 payment_channel="in store")


def test_tick_syncs_transactions_and_advances_cursor():
    from tests.fakes import FakePlaidProvider
    _seed_item(products=("transactions",))
    delta = TransactionsDelta(added=[_txn("t1")], next_cursor="C2", has_more=False)
    providers.configure([FakePlaidProvider(accounts=[_acct()], delta=delta)])
    n = finance_sync.tick()
    assert n >= 2                                   # 1 account + 1 transaction
    assert len(store.finance_transactions()) == 1
    assert store.get_finance_item_cursor("itm1") == "C2"
    assert store.get_finance_item("itm1")["last_sync_at"] is not None


def test_tick_syncs_investments_branch():
    from tests.fakes import FakePlaidProvider
    _seed_item(products=("investments",))
    sec = NormalizedSecurity(source="plaid", source_id="s1", name="BTC", ticker_symbol="BTC",
                             type="cryptocurrency", close_price=Decimal("60000"), iso_currency="USD")
    hold = NormalizedHolding(source="plaid", item_id="itm1", account_id="brk", security_id="s1",
                             quantity=Decimal("0.05"), institution_value=Decimal("3000"),
                             iso_currency="USD")
    prov = FakePlaidProvider(holdings=([_acct("brk")], [sec], [hold]))
    providers.configure([prov])
    finance_sync.tick()
    assert len(store.finance_holdings()) == 1


def test_tick_flips_needs_reauth_on_auth_error():
    from tests.fakes import FakePlaidProvider
    _seed_item()
    providers.configure([FakePlaidProvider(raise_auth=True)])
    finance_sync.tick()
    assert store.get_finance_item("itm1")["status"] == "needs_reauth"


def test_disconnect_removes_synced_transactions():
    # Real Plaid txns carry no item_id; the sync must stamp it so disconnect cascades.
    from tests.fakes import FakePlaidProvider
    _seed_item(products=("transactions",))
    delta = TransactionsDelta(added=[_txn("t1")], next_cursor="C", has_more=False)
    for t in delta.added:        # simulate real Plaid: provider txns have no item_id
        t.item_id = ""
    providers.configure([FakePlaidProvider(accounts=[], delta=delta)])
    finance_sync.tick()
    assert len(store.finance_transactions()) == 1
    assert store.delete_finance_item("itm1") is True
    assert store.finance_transactions() == []   # cascade removed the synced txn
