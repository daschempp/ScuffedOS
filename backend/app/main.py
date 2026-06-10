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

from . import reminders
from .config import settings
from .errors import install_error_handlers
from .routers import assistant, calendar, habits, memory, nutrition, tasks


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the reminder tick alongside the server; stop it on shutdown."""
    loop_task: asyncio.Task | None = None
    if settings.reminders_enabled:
        loop_task = asyncio.create_task(reminders.run_loop())
    yield
    if loop_task is not None:
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task


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


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "scuffed-os-api"}
