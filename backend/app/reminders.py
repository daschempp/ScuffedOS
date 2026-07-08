"""Reminders that fire (M3) — a background tick + macOS notifications.

A plain asyncio loop (started from the app lifespan) wakes every
REMINDER_TICK_SECONDS, asks the store for unfired reminders past due on
still-open tasks, posts a notification for each, and stamps `fired_at`.
The catch-up is implicit: anything that came due while the laptop slept
fires on the next tick.

Delivery is `osascript -e 'display notification ...'` — works from a bare
process, no app bundle needed (the Tauri bundle lands in M8). Same test
seam as llm.py: `configure(fake_notifier)` swaps delivery, `configure(None)`
disables it.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import datetime

from .config import settings
from .store import store

logger = logging.getLogger("scuffed_os.reminders")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """Install a fake notifier (tests), None to disable, or reset to real."""
    global _override
    _override = override


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, body: str) -> None:
    if _override is None:
        return
    if _override != "unset":
        _override(title, body)
        return
    if sys.platform != "darwin":
        logger.info("notification (no macOS): %s — %s", title, body)
        return
    script = f"display notification {_applescript_str(body)} with title {_applescript_str(title)}"
    try:
        result = subprocess.run(
            ["osascript", "-e", script], check=False, capture_output=True, timeout=10
        )
        if result.returncode != 0:
            # The reminder is still consumed (no retry-spam), but delivery
            # problems must not be invisible.
            logger.warning(
                "osascript notification failed (rc=%s): %s",
                result.returncode, result.stderr.decode(errors="replace").strip(),
            )
    except Exception as exc:
        logger.warning("notification failed: %s", exc)


def tick(now: datetime | None = None) -> int:
    """Fire everything due; returns how many fired. Safe to call any time."""
    try:
        due = store.due_reminders(now)
    except RuntimeError:  # no DATABASE_URL configured — nothing to do
        return 0
    for r in due:
        notify(r["task_label"], r["label"] or "Task reminder")
        store.mark_reminder_fired(r["id"], now)
    return len(due)


async def run_loop() -> None:
    """The lifespan background task; ticks forever until cancelled."""
    logger.info("reminder loop started (every %ss)", settings.reminder_tick_seconds)
    while True:
        try:
            fired = await asyncio.to_thread(tick)
            if fired:
                logger.info("fired %d reminder(s)", fired)
        except Exception:
            logger.exception("reminder tick failed")
        await asyncio.sleep(settings.reminder_tick_seconds)
