"""Application settings, loaded from the environment (a backend/.env file is supported).

Copy .env.example to .env for local overrides. Settings grow per milestone; only
add fields that are actually consumed somewhere.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Origins allowed to call the API directly (the Vite dev server; the dev proxy
    # makes most calls same-origin, so this is belt-and-braces).
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Anthropic API key — powers the real assistant from milestone M2 on.
    anthropic_api_key: str = ""

    # Postgres connection string (Supabase free tier in production — use the
    # *session pooler* string; the direct host is IPv6-only on the free tier).
    # Plain Postgres via SQLAlchemy; no Supabase SDKs anywhere. A bare
    # postgres:// / postgresql:// URL is normalized to the psycopg driver.
    database_url: str = ""

    # Owner stamped on every row. Single-user app today; the column exists so
    # a future multi-device/auth story doesn't need a schema rewrite.
    owner: str = "me"


settings = Settings()
