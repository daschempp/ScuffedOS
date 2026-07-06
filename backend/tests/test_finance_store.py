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
