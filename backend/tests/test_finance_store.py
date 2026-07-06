"""M7 Finance store — items CRUD/status, accounts, transactions delta,
holdings, budgets, summary, net worth. No network; SQLite via conftest."""
from datetime import date
from decimal import Decimal

from app.providers.base import (
    NormalizedAccount, NormalizedHolding, NormalizedItem,
    NormalizedSecurity, NormalizedTransaction, TransactionsDelta,
)
from app.store import store


def _item(item_id="itm1", products=("transactions",), name="Chase"):
    return NormalizedItem(item_id=item_id, institution_id="ins_1",
                          institution_name=name, products=list(products))


def test_upsert_finance_item_is_idempotent_and_hides_token():
    first = store.upsert_finance_item(_item(), access_token="tok-A")
    second = store.upsert_finance_item(_item(name="Chase Bank"), access_token="tok-B")
    assert first["item_id"] == second["item_id"]
    assert second["institution_name"] == "Chase Bank"
    assert "access_token" not in second           # never serialized to clients
    assert len(store.list_finance_items()) == 1
    # Token retrievable only via the server-side accessor.
    assert store.get_finance_item_token("itm1") == "tok-B"


def test_finance_item_status_cursor_synced_and_delete():
    store.upsert_finance_item(_item(), access_token="tok")
    store.set_finance_item_cursor("itm1", "CURSOR-9")
    store.set_finance_item_status("itm1", "needs_reauth")
    row = store.get_finance_item("itm1")
    assert row["status"] == "needs_reauth"
    status = store.finance_status()
    assert status["connected"] is True and len(status["items"]) == 1
    assert store.delete_finance_item("itm1") is True
    assert store.list_finance_items() == []
    assert store.delete_finance_item("itm1") is False


def _acct(source_id="acc1", item_id="itm1", type="depository", subtype="checking",
          current="100.00", available="90.00"):
    return NormalizedAccount(source="plaid", source_id=source_id, item_id=item_id,
                             name="Checking", official_name=None, mask="1234",
                             type=type, subtype=subtype,
                             current_balance=Decimal(current),
                             available_balance=Decimal(available), iso_currency="USD")


def _txn(source_id="t1", amount="64.20", d=date(2026, 6, 8), primary="FOOD_AND_DRINK",
         detailed="FOOD_AND_DRINK_GROCERIES", account_id="acc1"):
    return NormalizedTransaction(source="plaid", source_id=source_id, account_id=account_id,
                                 item_id="itm1", name="Whole Foods", merchant_name="Whole Foods",
                                 amount=Decimal(amount), iso_currency="USD", date=d,
                                 authorized_date=None, pending=False,
                                 category_primary=primary, category_detailed=detailed,
                                 payment_channel="in store")


def test_account_upsert_idempotent_and_serialized():
    store.upsert_finance_account(_acct())
    store.upsert_finance_account(_acct(current="150.00"))
    accs = store.list_finance_accounts()
    assert len(accs) == 1
    assert accs[0]["current_balance"] == 150.0
    assert accs[0]["type"] == "depository"


def test_apply_transaction_delta_upserts_and_removes():
    n = store.apply_transaction_delta(TransactionsDelta(
        added=[_txn("t1"), _txn("t2", amount="-3200.00", primary="INCOME")],
        modified=[], removed=[], next_cursor="C1", has_more=False))
    assert n == 2
    txns = store.finance_transactions()
    assert {t["source_id"] for t in txns} == {"t1", "t2"}
    income = next(t for t in txns if t["source_id"] == "t2")
    assert income["positive"] is True                 # amount < 0 → inflow
    # A second page modifies t1 and removes t2.
    store.apply_transaction_delta(TransactionsDelta(
        added=[], modified=[_txn("t1", amount="70.00")], removed=["t2"],
        next_cursor="C2", has_more=False))
    txns = store.finance_transactions()
    assert len(txns) == 1
    assert txns[0]["source_id"] == "t1" and txns[0]["amount"] == 70.0


def test_finance_transactions_filters():
    store.apply_transaction_delta(TransactionsDelta(
        added=[_txn("t1", account_id="acc1", primary="FOOD_AND_DRINK"),
               _txn("t2", account_id="acc2", primary="TRANSPORTATION")],
        modified=[], removed=[], next_cursor="C1", has_more=False))
    assert len(store.finance_transactions(account_id="acc1")) == 1
    assert len(store.finance_transactions(category="TRANSPORTATION")) == 1


def test_finance_transactions_days_filter_excludes_older_than_cutoff():
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    store.apply_transaction_delta(TransactionsDelta(
        added=[_txn("recent", d=today - timedelta(days=2)),
               _txn("old", d=today - timedelta(days=40))],
        modified=[], removed=[], next_cursor="C", has_more=False))
    ids = {t["source_id"] for t in store.finance_transactions(days=10)}
    assert "recent" in ids and "old" not in ids


def _sec(source_id="s1", name="Bitcoin", ticker="BTC", type="cryptocurrency"):
    return NormalizedSecurity(source="plaid", source_id=source_id, name=name,
                              ticker_symbol=ticker, type=type,
                              close_price=Decimal("60000"), iso_currency="USD")


def _hold(security_id="s1", account_id="acc9", qty="0.05", value="3000"):
    return NormalizedHolding(source="plaid", item_id="itm1", account_id=account_id,
                             security_id=security_id, quantity=Decimal(qty),
                             cost_basis=Decimal("2000"), institution_value=Decimal(value),
                             institution_price=Decimal("60000"), iso_currency="USD")


def test_holdings_join_security_and_flag_crypto():
    store.upsert_finance_security(_sec())
    store.upsert_finance_security(_sec("s2", "Apple", "AAPL", "equity"))
    store.upsert_finance_holding(_hold("s1", value="3000"))
    store.upsert_finance_holding(_hold("s2", account_id="acc9", value="22640"))
    holdings = store.finance_holdings()
    assert len(holdings) == 2
    btc = next(h for h in holdings if h["ticker"] == "BTC")
    assert btc["is_crypto"] is True
    assert btc["value"] == 3000.0
    assert btc["name"] == "Bitcoin"
    aapl = next(h for h in holdings if h["ticker"] == "AAPL")
    assert aapl["is_crypto"] is False


def test_holding_upsert_idempotent_by_account_and_security():
    store.upsert_finance_security(_sec())
    store.upsert_finance_holding(_hold(value="3000"))
    store.upsert_finance_holding(_hold(value="3200"))     # same account+security
    holdings = store.finance_holdings()
    assert len(holdings) == 1 and holdings[0]["value"] == 3200.0


def test_finance_holdings_falls_back_when_security_missing():
    # A holding whose security_id was never registered via upsert_finance_security.
    store.upsert_finance_holding(_hold("nonesuch", value="500"))
    h = next(x for x in store.finance_holdings() if x["security_id"] == "nonesuch")
    assert h["name"] == "nonesuch"
    assert h["ticker"] is None
    assert h["type"] == ""
    assert h["is_crypto"] is False
