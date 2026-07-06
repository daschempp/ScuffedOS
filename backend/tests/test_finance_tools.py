"""M7 assistant tools — finance reads + local budget writes (no Plaid writes)."""
import json

from app import tools
from app.store import store


def test_get_finance_summary_tool_returns_finance_action():
    result, action = tools.execute("get_finance_summary", {"month": "2026-06"})
    assert action["screen"] == "finance"
    assert "balance" in json.loads(result)


def test_reallocate_budget_tool_moves_limit():
    store.upsert_budgets("2026-06", [
        {"category": "Dining out", "limit_amount": 250},
        {"category": "Savings", "limit_amount": 600}])
    result, action = tools.execute("reallocate_budget", {
        "month": "2026-06", "from_category": "Dining out",
        "to_category": "Savings", "amount": 120})
    assert action["screen"] == "finance"
    budgets = {b["category"]: b for b in json.loads(result)["budgets"]}
    assert budgets["Savings"]["limit_amount"] == 720.0


def test_finance_tools_registered_in_definitions():
    names = {d["name"] for d in tools.DEFINITIONS}
    assert {"get_finance_summary", "get_transactions", "get_networth",
            "get_holdings", "get_budgets", "set_budget", "reallocate_budget"} <= names
