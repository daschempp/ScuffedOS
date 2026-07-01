"""Scuffed OS — FastAPI backend entry point.

Backs the desktop dashboard: assistant chat, tasks, second-brain memories,
and (M3) calendar, habits, and nutrition. Run with:

    uvicorn app.main:app --port 8000      # from the backend/ directory

The Vite dev server proxies /api -> http://localhost:8000 (see frontend/vite.config.js),
and CORS is also enabled for direct access from the dev origin.
"""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import fitness_sync, reminders
from .config import settings
from .errors import install_error_handlers
from .routers import assistant, calendar, fitness, habits, memory, nutrition, tasks


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the reminder tick and the fitness-sync loop alongside the server;
    stop them on shutdown."""
    reminder_task: asyncio.Task | None = None
    fitness_task: asyncio.Task | None = None
    if settings.reminders_enabled:
        reminder_task = asyncio.create_task(reminders.run_loop())
    if settings.fitness_sync_enabled:
        fitness_task = asyncio.create_task(fitness_sync.run_loop())
    yield
    for task in (reminder_task, fitness_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Scuffed OS API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app)

app.include_router(assistant.router)
app.include_router(tasks.router)
app.include_router(memory.router)
app.include_router(calendar.router)
app.include_router(habits.router)
app.include_router(nutrition.router)
app.include_router(fitness.router)
app.include_router(fitness.auth_router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "scuffed-os-api"}
