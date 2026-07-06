"""M7 Finance — normalized dataclasses + ORM models (contract §2/§4)."""
from datetime import date
from decimal import Decimal

from app.providers.base import (
    NormalizedAccount,
    NormalizedHolding,
    NormalizedItem,
    NormalizedSecurity,
    NormalizedTransaction,
    PlaidProvider,
    TransactionsDelta,
)


def test_normalized_dataclasses_construct():
    item = NormalizedItem(item_id="itm1", institution_id="ins_1",
                          institution_name="Chase", products=["transactions"])
    assert item.products == ["transactions"]

    acct = NormalizedAccount(
        source="plaid", source_id="acc1", item_id="itm1", name="Checking",
        official_name=None, mask="1234", type="depository", subtype="checking",
        current_balance=Decimal("100.50"), available_balance=Decimal("90.00"),
        iso_currency="USD",
    )
    assert acct.current_balance == Decimal("100.50")

    txn = NormalizedTransaction(
        source="plaid", source_id="t1", account_id="acc1", item_id="itm1",
        name="Whole Foods", merchant_name="Whole Foods", amount=Decimal("64.20"),
        iso_currency="USD", date=date(2026, 6, 8), authorized_date=None,
        pending=False, category_primary="FOOD_AND_DRINK",
        category_detailed="FOOD_AND_DRINK_GROCERIES", payment_channel="in store",
    )
    assert txn.amount == Decimal("64.20")

    sec = NormalizedSecurity(source="plaid", source_id="s1", name="Bitcoin",
                             ticker_symbol="BTC", type="cryptocurrency",
                             close_price=Decimal("60000"), iso_currency="USD",
                             is_cash_equivalent=False)
    assert sec.type == "cryptocurrency"

    hold = NormalizedHolding(source="plaid", item_id="itm1", account_id="acc9",
                             security_id="s1", quantity=Decimal("0.05"),
                             cost_basis=Decimal("2000"), institution_value=Decimal("3000"),
                             institution_price=Decimal("60000"), iso_currency="USD")
    assert hold.institution_value == Decimal("3000")

    delta = TransactionsDelta(added=[txn], modified=[], removed=["t9"],
                              next_cursor="CUR2", has_more=False)
    assert delta.removed == ["t9"]


def test_plaid_provider_is_runtime_checkable():
    class Stub:
        name = "plaid"
        def create_link_token(self, kind): return {}
        def get_link_public_token(self, link_token): return None
        def exchange_public_token(self, public_token): return ("at", "itm1")
        def get_item(self, access_token): return None
        def get_accounts(self, access_token): return []
        def sync_transactions(self, access_token, cursor): return None
        def get_holdings(self, access_token): return ([], [], [])
        def remove_item(self, access_token): return None
    assert isinstance(Stub(), PlaidProvider)
