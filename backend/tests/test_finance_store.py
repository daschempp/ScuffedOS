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


def test_budget_bucket_mapping():
    from app.store import budget_bucket
    assert budget_bucket("FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES") == "Groceries"
    assert budget_bucket("FOOD_AND_DRINK", "FOOD_AND_DRINK_RESTAURANT") == "Dining out"
    assert budget_bucket("RENT_AND_UTILITIES", "") == "Rent & bills"
    assert budget_bucket("TRANSPORTATION", "") == "Transport"
    assert budget_bucket("TRANSFER_OUT", "TRANSFER_OUT_SAVINGS") == "Savings"
    assert budget_bucket("ENTERTAINMENT", "") == "Entertainment"


def test_budgets_have_all_categories_with_derived_spend():
    from app.store import BUDGET_CATEGORIES
    store.upsert_budgets("2026-06", [{"category": "Groceries", "limit_amount": 400}])
    # A June grocery outflow (+ amount) and an inflow (should not count as spend).
    store.apply_transaction_delta(TransactionsDelta(
        added=[_txn("t1", amount="64.20", d=date(2026, 6, 8),
                    primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_GROCERIES"),
               _txn("t2", amount="-500.00", d=date(2026, 6, 5), primary="INCOME")],
        modified=[], removed=[], next_cursor="C1", has_more=False))
    budgets = store.finance_budgets("2026-06")
    assert len(budgets) == len(BUDGET_CATEGORIES)
    groceries = next(b for b in budgets if b["category"] == "Groceries")
    assert groceries["limit_amount"] == 400.0
    assert groceries["spent"] == 64.20
    assert groceries["color"]  # non-empty tint


def test_reallocate_budget_moves_limit():
    store.upsert_budgets("2026-06", [
        {"category": "Dining out", "limit_amount": 250},
        {"category": "Savings", "limit_amount": 600}])
    store.reallocate_budget("2026-06", "Dining out", "Savings", 120)
    budgets = {b["category"]: b for b in store.finance_budgets("2026-06")}
    assert budgets["Dining out"]["limit_amount"] == 130.0
    assert budgets["Savings"]["limit_amount"] == 720.0


def test_finance_summary_income_spent_and_deltas():
    store.upsert_finance_account(_acct("acc1", current="4820.50", available="4820.50"))
    store.apply_transaction_delta(TransactionsDelta(added=[
        _txn("i1", amount="-3200.00", d=date(2026, 6, 1), primary="INCOME"),
        _txn("s1", amount="1450.00", d=date(2026, 6, 3), primary="RENT_AND_UTILITIES"),
        _txn("s2", amount="64.20", d=date(2026, 6, 8), primary="FOOD_AND_DRINK"),
        _txn("x1", amount="500.00", d=date(2026, 5, 5), primary="FOOD_AND_DRINK"),  # May
    ], modified=[], removed=[], next_cursor="C", has_more=False))
    summ = store.finance_summary("2026-06")
    assert summ["balance"] == 4820.50
    assert summ["income_month"] == 3200.0
    assert round(summ["spent_month"], 2) == 1514.20
    # spent delta vs May (500.00 spent in May): 1514.20 - 500 = +1014.20
    assert round(summ["spent_delta"], 2) == 1014.20


def test_finance_networth_buckets():
    store.upsert_finance_account(_acct("cash", type="depository", subtype="checking",
                                       current="18050.00", available="18050.00"))
    store.upsert_finance_account(_acct("ira", type="investment", subtype="ira",
                                       current="21400.00", available="0"))
    store.upsert_finance_account(_acct("cc", type="credit", subtype="credit card",
                                       current="1200.00", available="0"))
    store.upsert_finance_security(_sec("s1", "Bitcoin", "BTC", "cryptocurrency"))
    store.upsert_finance_security(_sec("s2", "VTI", "VTI", "etf"))
    store.upsert_finance_holding(_hold("s1", account_id="brk", value="3400"))    # crypto
    store.upsert_finance_holding(_hold("s2", account_id="brk", value="48200"))   # investments
    nw = store.finance_networth()
    buckets = {b["name"]: b["value"] for b in nw["buckets"]}
    assert buckets["Cash"] == 18050.0
    assert buckets["Crypto"] == 3400.0
    assert buckets["Investments"] == 48200.0
    assert buckets["Retirement"] == 21400.0
    assert buckets["Credit/Loans"] == -1200.0
    assert round(nw["total"], 2) == round(18050 + 3400 + 48200 + 21400 - 1200, 2)


def test_delete_finance_item_prunes_holdings_and_orphan_securities():
    from sqlalchemy import select
    from app.models import FinanceSecurity
    store.upsert_finance_item(_item("itm1", products=("investments",)), access_token="tok")
    store.upsert_finance_account(_acct("brk", type="investment", subtype="brokerage",
                                       current="3000.00", available="0"))
    store.upsert_finance_security(_sec("s1"))
    store.upsert_finance_holding(_hold("s1", account_id="brk", value="3000"))
    assert len(store.finance_holdings()) == 1
    assert store.delete_finance_item("itm1") is True
    # holdings gone, net worth back to zero, and the orphaned security physically pruned
    assert store.finance_holdings() == []
    assert store.finance_networth()["total"] == 0.0
    with store._session() as s:
        assert s.scalars(select(FinanceSecurity)).all() == []


def test_delete_finance_item_keeps_security_referenced_by_surviving_investment_tx():
    # A security referenced ONLY by a surviving item's investment-tx (no holding)
    # must NOT be pruned when a different item is disconnected.
    from sqlalchemy import select
    from app.models import FinanceSecurity
    from app.providers.base import NormalizedInvestmentTransaction
    store.upsert_finance_item(_item("itmA", products=("transactions",)), access_token="tokA")
    store.upsert_finance_item(_item("itmB", products=("investments",)), access_token="tokB")
    store.upsert_finance_security(_sec("s1"))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it1", item_id="itmB", account_id="brk", security_id="s1",
        type="buy", quantity=Decimal("0.01"), amount=Decimal("600"), date=date(2026, 6, 10)))
    assert store.delete_finance_item("itmA") is True
    with store._session() as s:
        survivors = {x.source_id for x in s.scalars(select(FinanceSecurity)).all()}
    assert "s1" in survivors            # still referenced by itmB's investment-tx


def test_upsert_and_cascade_slice2_tables():
    from datetime import date
    from app.providers.base import (
        NormalizedItem, NormalizedRecurringStream, NormalizedLiability,
        NormalizedInvestmentTransaction,
    )
    store.upsert_finance_item(NormalizedItem(item_id="itm1", institution_id="ins_1",
                                             institution_name="Chase", products=["transactions"]),
                              access_token="tok")
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="str1", item_id="itm1", account_id="a1",
        stream_type="outflow", description="Netflix", merchant_name="Netflix",
        category_primary="ENTERTAINMENT", average_amount=Decimal("15.49"),
        frequency="MONTHLY", predicted_next_date=date(2026, 7, 12)))
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="cc1",
        liability_type="credit", minimum_payment=Decimal("35"),
        next_payment_due_date=date(2026, 7, 15)))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it1", item_id="itm1", account_id="brk", security_id="s1",
        type="buy", quantity=Decimal("0.01"), amount=Decimal("600"), date=date(2026, 6, 10)))
    # idempotent re-upsert keeps one row
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="str1", item_id="itm1", account_id="a1",
        stream_type="outflow", description="Netflix", merchant_name="Netflix",
        average_amount=Decimal("16.49"), frequency="MONTHLY"))
    from sqlalchemy import select as _select
    from app.models import FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction
    with store._session() as s:
        assert len(s.scalars(_select(FinanceRecurring)).all()) == 1        # re-upsert didn't duplicate
        assert len(s.scalars(_select(FinanceInvestmentTransaction)).all()) == 1
    # disconnect cascades all three new tables
    assert store.delete_finance_item("itm1") is True
    with store._session() as s:
        assert s.scalars(_select(FinanceRecurring)).all() == []
        assert s.scalars(_select(FinanceLiability)).all() == []
        assert s.scalars(_select(FinanceInvestmentTransaction)).all() == []


def test_subscriptions_and_bills_split_and_merge():
    from datetime import date
    from app.providers.base import NormalizedRecurringStream, NormalizedLiability
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="sub1", item_id="itm1", account_id="a1", stream_type="outflow",
        description="Netflix", merchant_name="Netflix", category_primary="ENTERTAINMENT",
        average_amount=Decimal("15.49"), frequency="MONTHLY", predicted_next_date=date(2026, 7, 12),
        is_active=True))
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="bill1", item_id="itm1", account_id="a1", stream_type="outflow",
        description="Verizon", merchant_name="Verizon", category_primary="RENT_AND_UTILITIES",
        average_amount=Decimal("70"), frequency="MONTHLY", predicted_next_date=date(2026, 7, 16),
        is_active=True))
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="pay1", item_id="itm1", account_id="a1", stream_type="inflow",
        description="Payroll", merchant_name="Acme", category_primary="INCOME",
        average_amount=Decimal("2500"), frequency="BIWEEKLY", is_active=True))
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="cc1", liability_type="credit",
        minimum_payment=Decimal("35"), next_payment_due_date=date(2026, 7, 15)))
    subs = store.finance_subscriptions()
    assert [s["name"] for s in subs] == ["Netflix"]           # inflow + bill excluded
    assert subs[0]["amount"] == 15.49
    bills = store.finance_bills()
    names = {b["name"] for b in bills}
    assert "Verizon" in names                                 # utility recurring stream = bill
    assert "Netflix" not in names                             # entertainment stream = subscription, not bill
    # recurring bill + liability both present, sorted by due date
    assert any(b["kind"] == "recurring" for b in bills)
    assert any(b["kind"] == "liability" and b["amount"] == 35.0 for b in bills)
    assert [b["due_date"] for b in bills] == sorted(b["due_date"] for b in bills)


def test_finance_bills_resolves_liability_display_name():
    # The liability bill's name must resolve to the human account name, not the
    # opaque Plaid account_id hash. Mirrors finance_holdings' security resolve.
    from app.providers.base import NormalizedAccount, NormalizedLiability
    store.upsert_finance_account(NormalizedAccount(
        source="plaid", source_id="acc_hash_xyz", item_id="itm1", name="Chase Sapphire",
        official_name=None, mask="1234", type="credit", subtype="credit card",
        current_balance=Decimal("1200.00"), available_balance=Decimal("0"), iso_currency="USD"))
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="acc_hash_xyz",
        liability_type="credit", minimum_payment=Decimal("35"),
        next_payment_due_date=date(2026, 7, 15)))
    bill = next(b for b in store.finance_bills() if b["kind"] == "liability")
    assert bill["name"] == "Chase Sapphire"       # resolved, not the acc_hash_xyz hash
    assert bill["sub"] == "credit"


def test_investment_transactions_join_securities_newest_first():
    from datetime import date
    from app.providers.base import NormalizedSecurity, NormalizedInvestmentTransaction
    store.upsert_finance_security(NormalizedSecurity(
        source="plaid", source_id="s1", name="Bitcoin", ticker_symbol="BTC",
        type="cryptocurrency", iso_currency="USD"))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it1", item_id="itm1", account_id="brk", security_id="s1",
        type="buy", name="BUY BTC", quantity=Decimal("0.01"), amount=Decimal("600"),
        price=Decimal("60000"), date=date(2026, 6, 10)))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it2", item_id="itm1", account_id="brk", security_id="s1",
        type="sell", name="SELL BTC", quantity=Decimal("-0.005"), amount=Decimal("-300"),
        date=date(2026, 6, 11)))
    ledger = store.finance_investment_transactions()
    assert ledger[0]["type"] == "sell"          # newest first (2026-06-11 before 2026-06-10)
    assert ledger[0]["ticker"] == "BTC"
    assert ledger[1]["type"] == "buy" and ledger[1]["amount"] == 600.0


def test_bills_appear_in_events_between_read_only():
    from datetime import datetime, timezone
    from app.providers.base import NormalizedLiability
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="cc1", liability_type="credit",
        minimum_payment=Decimal("35"), next_payment_due_date=__import__("datetime").date(2026, 7, 15)))
    occ = store.events_between(datetime(2026, 7, 1, tzinfo=timezone.utc),
                              datetime(2026, 7, 31, tzinfo=timezone.utc))
    fin = [o for o in occ if str(o["id"]).startswith("finance:")]
    assert fin and fin[0]["editable"] is False and fin[0]["source"] == "finance"
    # out-of-window excluded
    occ2 = store.events_between(datetime(2026, 8, 1, tzinfo=timezone.utc),
                               datetime(2026, 8, 31, tzinfo=timezone.utc))
    assert [o for o in occ2 if str(o["id"]).startswith("finance:")] == []


def test_expanded_budget_categories_and_bucket_mapping():
    from app.store import BUDGET_CATEGORIES, budget_bucket
    assert BUDGET_CATEGORIES == ["Groceries", "Dining out", "Rent & bills", "Transport",
                                 "Shopping", "Entertainment", "Health", "Travel",
                                 "Savings", "Other"]
    assert budget_bucket("GENERAL_MERCHANDISE") == "Shopping"
    assert budget_bucket("ENTERTAINMENT") == "Entertainment"
    assert budget_bucket("MEDICAL") == "Health"
    assert budget_bucket("TRAVEL") == "Travel"
    got = {b["category"] for b in store.finance_budgets("2026-06")}
    assert len(got) == 10


def test_reallocate_clamps_at_zero():
    store.upsert_budgets("2026-06", [{"category": "Dining out", "limit_amount": 50}])
    store.reallocate_budget("2026-06", "Dining out", "Savings", 200)  # more than source has
    budgets = {b["category"]: b for b in store.finance_budgets("2026-06")}
    assert budgets["Dining out"]["limit_amount"] == 0.0               # drained, not negative
    # conserving: dest gains only what the source actually had (50), NOT the 200 asked
    assert budgets["Savings"]["limit_amount"] == 50.0
