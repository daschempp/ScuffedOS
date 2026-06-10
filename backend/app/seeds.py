"""Read-only sample data for domains that aren't built yet.

The assistant gets *read* tools over these so it can answer questions
truthfully-as-sample until each domain lands for real (fitness in M4,
finance in M6 — calendar/habits/nutrition went real in M3). Every payload
carries a `note` saying it's sample data so the model never presents it
as live.
"""
from __future__ import annotations

SAMPLE_NOTE = "SAMPLE DATA — this domain isn't connected yet; say so if the user asks about it."

FINANCE_SUMMARY = {
    "note": SAMPLE_NOTE + " Real bank data (Plaid) lands in M6.",
    "balance": 4820,
    "net_worth": 129050,
    "june_spending": {"spent": 1840, "budget": 2400},
    "dining": {"spent": 186, "budget": 250},
    "recent_transactions": [
        {"merchant": "Whole Foods", "category": "Groceries", "amount": -64.20},
        {"merchant": "Salary — Acme Inc", "category": "Income", "amount": 3200.00},
        {"merchant": "Spotify", "category": "Subscriptions", "amount": -11.99},
    ],
}

FITNESS_TODAY = {
    "note": SAMPLE_NOTE + " Real Whoop sync lands in M4.",
    "recovery_pct": 82,
    "sleep_hours": 7.4,
    "strain": 8.1,
}
