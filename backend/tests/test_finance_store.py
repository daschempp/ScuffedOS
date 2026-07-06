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
