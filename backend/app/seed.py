"""Populate the database with the design-prototype demo data.

Usage (from backend/, after `alembic upgrade head`):

    python -m app.seed

Idempotent: does nothing if any tasks already exist.
"""
from __future__ import annotations

from .store import store


def main() -> None:
    if store.seed_demo():
        print("Seeded demo tasks and memories.")
    else:
        print("Database already has tasks — left untouched.")


if __name__ == "__main__":
    main()
