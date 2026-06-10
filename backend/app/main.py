"""Scuffed OS — FastAPI backend entry point.

Stub endpoints that back the desktop dashboard's assistant chat, task list, and
second-brain memories. Run with:

    uvicorn app.main:app --port 8000      # from the backend/ directory

The Vite dev server proxies /api -> http://localhost:8000 (see frontend/vite.config.js),
and CORS is also enabled for direct access from the dev origin.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .errors import install_error_handlers
from .routers import assistant, memory, tasks

app = FastAPI(title="Scuffed OS API", version="0.1.0")

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


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "scuffed-os-api"}
