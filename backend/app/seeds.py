"""Read-only sample data for domains that aren't built yet.

The assistant gets *read* tools over these so it can answer questions
truthfully-as-sample until each domain lands for real (calendar/habits/
nutrition in M3, fitness in M4, finance in M6). Every payload carries a
`note` saying it's sample data so the model never presents it as live.
"""
from __future__ import annotations

SAMPLE_NOTE = "SAMPLE DATA — this domain isn't connected yet; say so if the user asks about it."

CALENDAR_TODAY = {
    "note": SAMPLE_NOTE + " Real calendar lands in M3.",
    "events": [
        {"time": "09:00", "title": "Deep work — Q3 planning", "meta": "Focus block"},
        {"time": "11:30", "title": "Standup with design", "meta": "Google Meet"},
        {"time": "13:00", "title": "Lunch — log it!", "meta": "Assistant reminder"},
        {"time": "16:00", "title": "Dentist", "meta": "12 Oak Street"},
    ],
}

NUTRITION_TODAY = {
    "note": SAMPLE_NOTE + " Real nutrition tracking lands in M3.",
    "calories": {"eaten": 1840, "goal": 2100},
    "protein_g": {"eaten": 138, "goal": 160},
    "water_cups": {"drunk": 5, "goal": 8},
}

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

HABITS_TODAY = {
    "note": SAMPLE_NOTE + " Real habit tracking lands in M3.",
    "done": 2,
    "total": 5,
    "habits": [
        {"name": "Morning workout", "done": True, "streak": 12},
        {"name": "Drink water", "done": True, "streak": 5},
        {"name": "Read 20 minutes", "done": False, "streak": 3},
        {"name": "Log meals", "done": False, "streak": 8},
        {"name": "No late screens", "done": False, "streak": 2},
    ],
}

FITNESS_TODAY = {
    "note": SAMPLE_NOTE + " Real Whoop sync lands in M4.",
    "recovery_pct": 82,
    "sleep_hours": 7.4,
    "strain": 8.1,
}
