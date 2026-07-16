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
    google_redirect_uri: str = ""   # empty -> GoogleProvider computes http://127.0.0.1:{scuffedos_port}/auth/google/callback at request time (M9 s2); a non-empty env value wins verbatim

    # Background email-sync (mirrors fitness_sync_enabled / fitness_sync_seconds).
    email_sync_enabled: bool = True
    email_sync_seconds: int = 900               # 15 min
    email_backfill_count: int = 50              # first-connect messages.list maxResults

    # ---- M6 School (Moodle) ----
    # Moodle web-services live at {moodle_base_url}/webservice/rest/server.php.
    # Auth is a static per-user wstoken (NOT OAuth) stored in provider_accounts,
    # never here. WolfWare is Shibboleth SSO (typeoflogin=3); the token is
    # obtained via the mobile launch flow / Security-keys page and pasted in.
    moodle_base_url: str = "https://moodle-courses2527.wolfware.ncsu.edu"   # no trailing slash
    moodle_sync_enabled: bool = True
    moodle_sync_seconds: int = 900              # 15 min; gentle (mobile-app cadence)
    moodle_backfill_days_ahead: int = 60        # deadline-timeline horizon

    # ---- M7 Finance (Plaid) ----
    # Plaid REST lives at {sandbox|production}.plaid.com. Credentials come from
    # the Plaid dashboard (Production keys once the use-case is approved); the
    # per-Item access_tokens live in the finance_items table, never here. The
    # connect flow is Hosted Link (a Plaid-hosted page), so no redirect URI is
    # registered and no public callback is needed. Read-only — we never move money.
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "production"                 # "sandbox" | "production"
    plaid_country_codes: list[str] = ["US"]

    # Background finance-sync (mirrors moodle_sync_enabled / moodle_sync_seconds).
    finance_sync_enabled: bool = True
    finance_sync_seconds: int = 1800              # 30 min
    plaid_backfill_days: int = 90                 # first-sync transaction history window

    # ---- M10 Contacts (local macOS AddressBook) ----
    # ISO-3166 alpha-2 fallback for E.164 normalization when contacts_sync_state
    # has not yet persisted a normalization_region. Task 5 upgrades the default
    # to _default_region() (system-locale sniff); "US" keeps Task 3 self-contained.
    contacts_default_region: str = "US"
    # Background contacts sync loop: armed only when True (per-tick consent is a
    # SEPARATE gate via contacts_sync_state.enabled). Defaults OFF (consent-gated).
    contacts_sync_enabled: bool = False
    contacts_sync_seconds: int = 21600           # 6h between background passes
    # Contact-photo store dir: relative -> resolved UNDER app_support_dir (never
    # ./data); absolute kept as-is. Resolved via contacts_photos_root().
    contacts_photos_dir: str = "contact_photos"

    def contacts_photos_root(self) -> str:
        """Absolute contact-photos root (App Support + contacts_photos_dir). The
        import is function-local to avoid a config <-> providers import cycle."""
        from .providers import contact_photos

        return contact_photos.resolve_root(self)

    # ---- M8 Ship / Tauri — managed local Postgres (packaged app only) ----
    # OFF by default: dev, CI, and the test suite are unchanged and use the
    # external DATABASE_URL exactly as today. The packaged .app sets this to 1,
    # which makes app/localdb.py boot a vendored Postgres under app_support_dir
    # and inject the socket DSN into database_url before the first DB call.
    scuffedos_managed_pg: bool = False           # env SCUFFEDOS_MANAGED_PG
    # Loopback port the backend listens on. Dev = uvicorn's 8000; packaged = the
    # random port the Tauri shell picks and exports as SCUFFEDOS_PORT (lib.rs).
    # GoogleProvider embeds this in the computed redirect URI when
    # google_redirect_uri is empty (M9 s2). No env_prefix/alias -> binds SCUFFEDOS_PORT.
    scuffedos_port: int = 8000                   # env SCUFFEDOS_PORT
    # Per-user state root; ~ is expanded by app/localdb.py, never here.
    app_support_dir: str = "~/Library/Application Support/ScuffedOS"
    managed_pg_superuser: str = "scuffedos"      # initdb -U role + DSN user
    managed_pg_dbname: str = "scuffedos"         # created DB + DSN dbname


settings = Settings()


# ---- M8 Ship / Tauri — secrets vault seam (Slice 2) ----
# Secrets resolve from the machine-bound vault ONLY when the field is empty
# after env/.env load, so a value in the environment (or a test's direct
# assignment) always wins and dev/CI are unchanged. A foreign/corrupt vault
# (machine id changed) is swallowed here and recovered via the Settings
# re-authenticate flow — startup never crashes on a bad vault.
import logging as _logging

from .secrets import SecretsVault, VaultDecryptError

_log = _logging.getLogger("scuffed_os.config")

# settings field name -> canonical vault key.
SECRET_FIELD_MAP: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "fdc_api_key": "FDC_API_KEY",
    "whoop_client_id": "WHOOP_CLIENT_ID",
    "whoop_client_secret": "WHOOP_CLIENT_SECRET",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "plaid_client_id": "PLAID_CLIENT_ID",
    "plaid_secret": "PLAID_SECRET",
}

# Field values that mean "not really set" and may be replaced by a vault value.
_UNSET_SENTINELS = {"", "DEMO_KEY"}

_vault: SecretsVault | None = None


def get_vault() -> SecretsVault:
    """Process-wide vault against app_support_dir. use_keyring only in the
    packaged app (SCUFFEDOS_MANAGED_PG); dev/CI use a file-only key."""
    global _vault
    if _vault is None:
        _vault = SecretsVault(
            settings.app_support_dir,
            use_keyring=settings.scuffedos_managed_pg,
        )
    return _vault


def resolve_secrets_from_vault(target: "Settings" = settings) -> None:
    """Fill empty/sentinel secret fields from the vault. Env/.env values win.
    A decrypt failure is logged and swallowed (recovered via Settings re-auth)."""
    try:
        stored = get_vault().read_all()
    except VaultDecryptError:
        _log.warning("secrets vault failed to decrypt; using env-only secrets "
                     "(re-authenticate in Settings to repair)")
        return
    except Exception as exc:  # defensive: never crash config import/startup
        _log.warning("secrets vault unavailable (%s); using env-only secrets", exc)
        return
    for field_name, vault_key in SECRET_FIELD_MAP.items():
        current = getattr(target, field_name, "")
        if current in _UNSET_SENTINELS:
            val = stored.get(vault_key)
            if val:
                setattr(target, field_name, val)


# Resolve once at import so lazy consumers (llm/food_db/providers) see vault
# values. Empty-only override keeps dev/CI/tests byte-for-byte unchanged.
resolve_secrets_from_vault(settings)
