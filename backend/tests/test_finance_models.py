"""M7 Finance — normalized dataclasses + ORM models (contract §2/§4)."""
from datetime import date
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.models import (
    FinanceAccount, FinanceBudget, FinanceHolding, FinanceItem,
    FinanceSecurity, FinanceTransaction,
)
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
        def create_link_token(self, kind, access_token=None): return {}
        def get_link_public_token(self, link_token): return None
        def exchange_public_token(self, public_token): return ("at", "itm1")
        def get_item(self, access_token): return None
        def get_accounts(self, access_token): return []
        def sync_transactions(self, access_token, cursor): return None
        def get_holdings(self, access_token): return ([], [], [])
        def get_recurring(self, access_token): return []
        def get_liabilities(self, access_token): return []
        def get_investment_transactions(self, access_token, start, end): return ([], [], [])
        def remove_item(self, access_token): return None
    assert isinstance(Stub(), PlaidProvider)


def test_finance_models_persist_and_roundtrip():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s, s.begin():
        s.add(FinanceItem(owner="me", source="plaid", source_id="itm1",
                          access_token="tok", institution_id="ins_1",
                          institution_name="Chase", products=["transactions"],
                          status="active"))
        s.add(FinanceAccount(owner="me", source="plaid", source_id="acc1",
                             item_id="itm1", name="Checking", type="depository",
                             subtype="checking", current_balance=Decimal("100.50"),
                             iso_currency="USD"))
        s.add(FinanceTransaction(owner="me", source="plaid", source_id="t1",
                                 account_id="acc1", item_id="itm1", name="WF",
                                 amount=Decimal("64.20"), iso_currency="USD",
                                 date=date(2026, 6, 8), category_primary="FOOD_AND_DRINK"))
        s.add(FinanceSecurity(owner="me", source="plaid", source_id="s1",
                              name="Bitcoin", ticker_symbol="BTC", type="cryptocurrency",
                              iso_currency="USD"))
        s.add(FinanceHolding(owner="me", account_id="acc9", item_id="itm1",
                             security_id="s1", quantity=Decimal("0.05"),
                             institution_value=Decimal("3000"), iso_currency="USD"))
        s.add(FinanceBudget(owner="me", category="Groceries", month="2026-06",
                            limit_amount=Decimal("400")))
    with Session() as s:
        acc = s.query(FinanceAccount).one()
        assert acc.current_balance == Decimal("100.50")
        assert s.query(FinanceHolding).one().quantity == Decimal("0.05")
    engine.dispose()


def test_slice2_models_persist_and_roundtrip():
    from datetime import date
    from app.db import Base, make_engine, make_session_factory
    from app.models import (
        FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction,
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s, s.begin():
        s.add(FinanceRecurring(owner="me", source="plaid", source_id="str1",
                               item_id="itm1", account_id="a1", stream_type="outflow",
                               description="Netflix", merchant_name="Netflix",
                               category_primary="ENTERTAINMENT", frequency="MONTHLY",
                               average_amount=Decimal("15.49"), last_amount=Decimal("15.49"),
                               last_date=date(2026, 6, 12), predicted_next_date=date(2026, 7, 12),
                               is_active=True, status="MATURE", iso_currency="USD"))
        s.add(FinanceLiability(owner="me", source="plaid", source_id="cc1",
                               item_id="itm1", account_id="cc1", liability_type="credit",
                               last_statement_balance=Decimal("1250.00"),
                               minimum_payment=Decimal("35.00"),
                               next_payment_due_date=date(2026, 7, 15),
                               apr_percentage=Decimal("19.99"), iso_currency="USD"))
        s.add(FinanceInvestmentTransaction(owner="me", source="plaid", source_id="it1",
                                           item_id="itm1", account_id="brk", security_id="s1",
                                           type="buy", subtype="buy", name="BUY BTC",
                                           quantity=Decimal("0.01"), amount=Decimal("600.00"),
                                           price=Decimal("60000"), fees=Decimal("1.50"),
                                           date=date(2026, 6, 10), iso_currency="USD"))
    with Session() as s:
        assert s.query(FinanceRecurring).one().average_amount == Decimal("15.49")
        assert s.query(FinanceLiability).one().next_payment_due_date == date(2026, 7, 15)
        assert s.query(FinanceInvestmentTransaction).one().quantity == Decimal("0.01")
    engine.dispose()


def test_slice2_normalized_dataclasses_construct():
    from datetime import date
    from app.providers.base import (
        NormalizedRecurringStream, NormalizedLiability, NormalizedInvestmentTransaction,
    )
    r = NormalizedRecurringStream(source="plaid", source_id="str1", item_id="itm1",
                                  account_id="a1", stream_type="outflow", description="Netflix",
                                  merchant_name="Netflix", average_amount=Decimal("15.49"),
                                  frequency="MONTHLY", predicted_next_date=date(2026, 7, 12))
    assert r.stream_type == "outflow" and r.average_amount == Decimal("15.49")
    liab = NormalizedLiability(source="plaid", source_id="cc1", item_id="itm1", account_id="cc1",
                               liability_type="credit", minimum_payment=Decimal("35"),
                               next_payment_due_date=date(2026, 7, 15))
    assert liab.liability_type == "credit"
    it = NormalizedInvestmentTransaction(source="plaid", source_id="it1", item_id="itm1",
                                         account_id="brk", security_id="s1", type="buy",
                                         quantity=Decimal("0.01"), amount=Decimal("600"),
                                         date=date(2026, 6, 10))
    assert it.type == "buy" and it.quantity == Decimal("0.01")
