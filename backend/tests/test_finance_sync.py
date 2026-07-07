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


def test_tick_syncs_recurring_and_liabilities_on_transactions_item():
    from datetime import date
    from tests.fakes import FakePlaidProvider
    from app.providers.base import NormalizedRecurringStream, NormalizedLiability
    _seed_item(products=("transactions",))
    rec = NormalizedRecurringStream(source="plaid", source_id="sub1", item_id="", account_id="a1",
                                    stream_type="outflow", description="Netflix", merchant_name="Netflix",
                                    category_primary="ENTERTAINMENT", average_amount=Decimal("15.49"),
                                    frequency="MONTHLY", predicted_next_date=date(2026, 7, 12))
    liab = NormalizedLiability(source="plaid", source_id="cc1", item_id="", account_id="cc1",
                               liability_type="credit", minimum_payment=Decimal("35"),
                               next_payment_due_date=date(2026, 7, 15))
    providers.configure([FakePlaidProvider(accounts=[_acct()], recurring=[rec], liabilities=[liab])])
    finance_sync.tick()
    assert len(store.finance_subscriptions()) == 1
    assert any(b["kind"] == "liability" for b in store.finance_bills())


def test_tick_syncs_investment_transactions_on_investments_item():
    from datetime import date
    from tests.fakes import FakePlaidProvider
    from app.providers.base import (
        NormalizedAccount, NormalizedSecurity, NormalizedInvestmentTransaction,
    )
    _seed_item(products=("investments",))
    sec = NormalizedSecurity(source="plaid", source_id="s1", name="BTC", ticker_symbol="BTC",
                             type="cryptocurrency", iso_currency="USD")
    it = NormalizedInvestmentTransaction(source="plaid", source_id="it1", item_id="itm1",
                                         account_id="brk", security_id="s1", type="buy",
                                         quantity=Decimal("0.01"), amount=Decimal("600"),
                                         date=date(2026, 6, 10))
    prov = FakePlaidProvider(holdings=([_acct("brk")], [sec], []),
                             investment_txns=([_acct("brk")], [sec], [it]))
    providers.configure([prov])
    finance_sync.tick()
    assert len(store.finance_investment_transactions()) == 1


def test_tick_multi_item_stamps_and_isolates():
    # Two items, two product branches: the loop must stamp each row with ITS
    # item_id (not the fixture's) and the disconnect cascade must not cross items.
    from datetime import date
    from tests.fakes import FakePlaidProvider
    from app.providers.base import (
        NormalizedRecurringStream, NormalizedLiability,
        NormalizedSecurity, NormalizedInvestmentTransaction,
    )
    from app.models import FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction
    from sqlalchemy import select
    # itm1 = transactions branch (recurring + liabilities); itm2 = investments branch.
    store.upsert_finance_item(
        NormalizedItem(item_id="itm1", institution_id="ins_1", institution_name="Chase",
                       products=["transactions"]), access_token="tok1")
    store.upsert_finance_item(
        NormalizedItem(item_id="itm2", institution_id="ins_2", institution_name="Coinbase",
                       products=["investments"]), access_token="tok2")
    # Fixtures carry a placeholder item_id="" — the sync loop must overwrite it.
    rec = NormalizedRecurringStream(source="plaid", source_id="sub1", item_id="", account_id="a1",
                                    stream_type="outflow", description="Netflix",
                                    merchant_name="Netflix", category_primary="ENTERTAINMENT",
                                    average_amount=Decimal("15.49"), frequency="MONTHLY",
                                    predicted_next_date=date(2026, 7, 12))
    liab = NormalizedLiability(source="plaid", source_id="cc1", item_id="", account_id="cc1",
                               liability_type="credit", minimum_payment=Decimal("35"),
                               next_payment_due_date=date(2026, 7, 15))
    sec = NormalizedSecurity(source="plaid", source_id="s1", name="BTC", ticker_symbol="BTC",
                             type="cryptocurrency", iso_currency="USD")
    itx = NormalizedInvestmentTransaction(source="plaid", source_id="it1", item_id="",
                                          account_id="brk", security_id="s1", type="buy",
                                          quantity=Decimal("0.01"), amount=Decimal("600"),
                                          date=date(2026, 6, 10))
    providers.configure([FakePlaidProvider(
        accounts=[_acct()], recurring=[rec], liabilities=[liab],
        holdings=([_acct("brk")], [sec], []),
        investment_txns=([_acct("brk")], [sec], [itx]))])
    finance_sync.tick()
    with store._session() as s:
        r = s.scalars(select(FinanceRecurring)).all()
        l = s.scalars(select(FinanceLiability)).all()
        it = s.scalars(select(FinanceInvestmentTransaction)).all()
        assert [x.item_id for x in r] == ["itm1"]        # stamped with itm1, not ""
        assert [x.item_id for x in l] == ["itm1"]
        assert [x.item_id for x in it] == ["itm2"]        # stamped with itm2
    # Disconnecting itm1 must NOT remove itm2's investment-tx (cross-item isolation).
    assert store.delete_finance_item("itm1") is True
    with store._session() as s:
        it2 = s.scalars(select(FinanceInvestmentTransaction)).all()
        assert [x.item_id for x in it2] == ["itm2"]       # itm2's row survives


def test_tick_survives_liabilities_absent():
    # Provider returns [] for liabilities (feature absent) — no crash, no rows.
    from tests.fakes import FakePlaidProvider
    _seed_item(products=("transactions",))
    providers.configure([FakePlaidProvider(accounts=[_acct()])])  # recurring/liabilities default []
    assert finance_sync.tick() >= 1
    assert store.finance_bills() == []
