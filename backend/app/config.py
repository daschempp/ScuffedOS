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

    # OpenAI API key — used *only* for Mem0's embedder (Anthropic has no
    # embeddings API). The assistant itself never calls OpenAI.
    openai_api_key: str = ""

    # Postgres connection string (Supabase free tier in production — use the
    # *session pooler* string; the direct host is IPv6-only on the free tier).
    # Plain Postgres via SQLAlchemy; no Supabase SDKs anywhere. A bare
    # postgres:// / postgresql:// URL is normalized to the psycopg driver.
    database_url: str = ""

    # Owner stamped on every row. Single-user app today; the column exists so
    # a future multi-device/auth story doesn't need a schema rewrite.
    owner: str = "me"

    # Assistant models — cheap/fast tier for chat, escalate for heavy work
    # (day planning now; email drafts in M5).
    assistant_model: str = "claude-haiku-4-5"
    assistant_heavy_model: str = "claude-opus-4-8"

    # Mem0 memory engine (self-hosted): Claude extraction + OpenAI embedder +
    # pgvector in the same Postgres. Dims are pinned to the embedder —
    # switching embedders means a new collection + re-embed (hence the
    # provider-tagged collection name below).
    memory_enabled: bool = True
    memory_llm_model: str = "claude-haiku-4-5"
    embedder_model: str = "text-embedding-3-small"
    embedder_dims: int = 1536
    mem0_collection: str = "mem0_memories_openai"
    # Mem0's change-history DB stays a local SQLite file (the one Mem0
    # artifact that doesn't live in Supabase).
    mem0_history_path: str = "./data/mem0_history.db"

    # Task attachments (M3): bytes live here, metadata stays on the task row.
    # Local app data, not Supabase — same frame as the Mem0 history file.
    attachments_dir: str = "./data/attachments"

    # Firing reminders (M3): a background tick scans for due reminders and
    # posts macOS notifications via osascript (works without an app bundle).
    reminders_enabled: bool = True
    reminder_tick_seconds: int = 30

    # USDA FoodData Central — resolves "a chicken wrap" to macros (M3).
    # DEMO_KEY works rate-limited; a free key from api.data.gov lifts it.
    fdc_api_key: str = "DEMO_KEY"

    # WHOOP fitness (M4). OAuth credentials come from the WHOOP developer
    # dashboard; the redirect URI must be registered there verbatim (WHOOP
    # rejects localhost — use a tunnel URL in dev, see the M4 design §14).
    # Tokens themselves are never config: they live in provider_accounts.
    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "https://scuffedcorporation.com/auth/whoop/callback"

    # Background pull-sync (mirrors reminders_enabled / reminder_tick_seconds).
    fitness_sync_enabled: bool = True
    fitness_sync_seconds: int = 1800            # 30 min
    whoop_backfill_days: int = 30               # first-connect backfill window

    # Google / Gmail (M5). OAuth credentials come from a Google Cloud "Web
    # application" OAuth 2.0 client; the redirect URI must be registered there
    # verbatim. Unlike WHOOP, Google permits http://localhost redirect URIs, so
    # local validation needs no tunnel. Tokens live in provider_accounts, never here.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Background email-sync (mirrors fitness_sync_enabled / fitness_sync_seconds).
    email_sync_enabled: bool = True
    email_sync_seconds: int = 900               # 15 min
    email_backfill_count: int = 50              # first-connect messages.list maxResults


settings = Settings()
