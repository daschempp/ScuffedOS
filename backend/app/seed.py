"""Populate the database with the design-prototype demo data.

Usage (from backend/, after `alembic upgrade head`):

    python -m app.seed

Idempotent per domain: each table seeds only if it's empty, so re-running
after a milestone adds the new domains without touching existing data.
"""
from __future__ import annotations

from .store import store


def main() -> None:
    if store.seed_demo():
        print("Seeded demo data (empty domains only).")
    else:
        print("Every domain already has data — left untouched.")


if __name__ == "__main__":
    main()
