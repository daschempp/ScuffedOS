"""Scuffed OS — FastAPI backend entry point.

Backs the desktop dashboard: assistant chat, tasks, second-brain memories,
and (M3) calendar, habits, and nutrition. Run with:

    uvicorn app.main:app --port 8000      # from the backend/ directory

The Vite dev server proxies /api -> http://localhost:8000 (see frontend/vite.config.js),
and CORS is also enabled for direct access from the dev origin.
"""
from __future__ import annotations

import asyncio
import atexit
import contextlib
import os
import signal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import contacts_sync, email_sync, finance_sync, fitness_sync, localdb, moodle_sync, reminders
from .config import settings
from .errors import install_error_handlers
from .routers import (
    assistant,
    calendar,
    connectors,
    email,
    finance,
    fitness,
    habits,
    insights,
    memory,
    moodle,
    nutrition,
    oauth,
    people,
    settings as settings_router,
    tasks,
)


_pg_stopped = False


def _resources_pgsql_dir() -> "os.PathLike | str":
    """Where the vendored pgsql tree lives before it's copied to App Support.

    The launcher stub exports RESOURCES_PGSQL_DIR pointing at
    Contents/Resources/pgsql. If unset (e.g. a manual managed-PG dev run),
    fall back to a sibling 'pgsql' of the app-support root.
    """
    env = os.environ.get("RESOURCES_PGSQL_DIR")
    if env:
        return env
    paths = localdb.resolve_paths(settings.app_support_dir)
    return paths.pgsql_dir


def _maybe_boot_managed_pg() -> None:
    if not settings.scuffedos_managed_pg:
        return
    dsn = localdb.boot(settings, _resources_pgsql_dir())
    settings.database_url = dsn


def _maybe_stop_managed_pg() -> None:
    global _pg_stopped
    if _pg_stopped or not settings.scuffedos_managed_pg:
        return
    _pg_stopped = True
    localdb.shutdown(settings)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the reminder tick and the fitness/email/moodle-sync loops alongside
    the server; stop them on shutdown. In the packaged app (SCUFFEDOS_MANAGED_PG)
    also boot a local Postgres before any DB-touching loop and stop it last."""
    _maybe_boot_managed_pg()
    reminder_task: asyncio.Task | None = None
    fitness_task: asyncio.Task | None = None
    email_task: asyncio.Task | None = None
    moodle_task: asyncio.Task | None = None
    finance_task: asyncio.Task | None = None
    contacts_task: asyncio.Task | None = None
    if settings.reminders_enabled:
        reminder_task = asyncio.create_task(reminders.run_loop())
    if settings.fitness_sync_enabled:
        fitness_task = asyncio.create_task(fitness_sync.run_loop())
    if settings.email_sync_enabled:
        email_task = asyncio.create_task(email_sync.run_loop())
    if settings.moodle_sync_enabled:
        moodle_task = asyncio.create_task(moodle_sync.run_loop())
    if settings.finance_sync_enabled:
        finance_task = asyncio.create_task(finance_sync.run_loop())
    if settings.contacts_sync_enabled:
        contacts_task = asyncio.create_task(contacts_sync.run_loop())
    yield
    for task in (reminder_task, fitness_task, email_task, moodle_task, finance_task, contacts_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    _maybe_stop_managed_pg()


app = FastAPI(title="Scuffed OS API", version="0.1.0", lifespan=lifespan)

# Hard-exit safety net: the lifespan post-yield block does not run on SIGTERM/
# hard exit, so also stop the managed Postgres from atexit + a SIGTERM handler.
# Both call the idempotent _maybe_stop_managed_pg (guarded by _pg_stopped), so a
# clean shutdown never double-stops. On the flag-off dev path these are no-ops.
atexit.register(_maybe_stop_managed_pg)


def _sigterm_stop(_signum, _frame):
    _maybe_stop_managed_pg()
    raise SystemExit(0)


try:
    signal.signal(signal.SIGTERM, _sigterm_stop)
except ValueError:
    # signal.signal only works on the main thread; TestClient/threaded runs skip it.
    pass

# The packaged Tauri webview loads from a custom-protocol origin (NOT the Vite
# dev server), then fetches the sidecar over http://127.0.0.1:<port> — a cross-
# origin request. Every api.js call sends Content-Type: application/json, which
# forces a CORS preflight even on GETs, so an unlisted webview origin makes
# WKWebView block *every* backend call (the Connectors panel is just where that
# surfaces loudly). Allow the webview origins alongside the env-configured ones.
# Platform origins: macOS/iOS `tauri://localhost`; Windows/Linux
# `http://tauri.localhost`; Android `https://tauri.localhost`.
_TAURI_WEBVIEW_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[*settings.cors_origins, *_TAURI_WEBVIEW_ORIGINS],
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app)

app.include_router(assistant.router)
app.include_router(tasks.router)
app.include_router(memory.router)
app.include_router(people.router)
app.include_router(calendar.router)
app.include_router(habits.router)
app.include_router(nutrition.router)
app.include_router(fitness.router)
app.include_router(oauth.router)
app.include_router(oauth.auth_router)
app.include_router(email.router)
app.include_router(moodle.router)
app.include_router(finance.router)
app.include_router(connectors.router)
app.include_router(insights.router)
app.include_router(settings_router.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "scuffed-os-api"}


@app.get("/health", tags=["meta"])
def ship_health() -> dict:
    """Bare-root health probe for the Tauri sidecar gate.

    Intentionally DB-free: returns 200 as soon as uvicorn is serving, so the
    Rust shell can show the window without waiting on managed-Postgres. The
    /api/health route above is the frontend-facing one behind the Vite proxy.
    """
    return {"status": "ok"}
