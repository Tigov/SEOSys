"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Local-only defaults. Production refuses to start while any of these is still in use (see production_problems).
DEV_DATABASE_URL = "postgresql+psycopg://seosys_app:seosys_app_local@127.0.0.1:5432/seosys"
DEV_DATABASE_OWNER_URL = "postgresql+psycopg://seosys_owner:seosys_owner_local@127.0.0.1:5432/seosys"
DEV_ENCRYPTION_KEY = "ZGV2LW9ubHkta2V5LWRvLW5vdC11c2UtaW4tcHJvZCE="  # 32 bytes, development only
DEV_DEMO_SITE_SECRET = "local-dev-secret-change-me"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in _env(name).split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    app_name: str = "SEOSys"
    app_base_url: str = field(default_factory=lambda: _env("APP_BASE_URL", "http://localhost:8000").rstrip("/"))

    # Postgres. The app connects as a role that owns nothing (row-level security applies); migrations use the owner.
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", DEV_DATABASE_URL))
    database_owner_url: str = field(default_factory=lambda: _env("DATABASE_OWNER_URL", DEV_DATABASE_OWNER_URL))
    db_pool_size: int = field(default_factory=lambda: int(_env("DB_POOL_SIZE", "5")))

    # Field encryption (AES-256-GCM). Old keys decrypt only, as "v1=<key>,v2=<key>".
    encryption_key: str = field(default_factory=lambda: _env("APP_ENCRYPTION_KEY", DEV_ENCRYPTION_KEY))
    encryption_key_version: int = field(default_factory=lambda: int(_env("APP_ENCRYPTION_KEY_VERSION", "1")))
    encryption_keys_old: tuple[str, ...] = field(default_factory=lambda: _list("APP_ENCRYPTION_KEYS_OLD"))

    # Email (Mailpit locally).
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", "localhost"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "1025")))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    smtp_tls: bool = field(default_factory=lambda: _bool("SMTP_TLS", False))
    mail_from: str = field(default_factory=lambda: _env("MAIL_FROM", "SEOSys <no-reply@seosys.local>"))

    # Stripe (test mode locally).
    stripe_secret_key: str = field(default_factory=lambda: _env("STRIPE_SECRET_KEY"))
    stripe_webhook_secret: str = field(default_factory=lambda: _env("STRIPE_WEBHOOK_SECRET"))

    # First admin, created by `python -m seo_platform seed`.
    seed_admin_email: str = field(default_factory=lambda: _env("SEED_ADMIN_EMAIL"))
    seed_admin_password: str = field(default_factory=lambda: _env("SEED_ADMIN_PASSWORD"))

    # Demo client website (development only).
    demo_site_url: str = field(default_factory=lambda: _env("DEMO_SITE_URL", "http://127.0.0.1:8001"))
    demo_site_secret: str = field(default_factory=lambda: _env("DEMO_SITE_SECRET", DEV_DEMO_SITE_SECRET))
    # Crawling local addresses is required for the demo site. In production this is False (SSRF guard).
    allow_private_hosts: bool = field(default_factory=lambda: _bool("ALLOW_PRIVATE_HOSTS", True))
    max_pages: int = field(default_factory=lambda: int(_env("CRAWL_MAX_PAGES", "50")))
    crawl_user_agent: str = "SEOSysBot/1.0 (+https://seosys.local/bot)"
    # Optional real LLM. Without a key the platform uses a deterministic offline writer.
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("SEO_LLM_MODEL", "claude-haiku-5-5"))
    default_monthly_budget_usd: float = field(default_factory=lambda: float(_env("CLIENT_MONTHLY_BUDGET_USD", "80")))
    # Google: one OAuth web client for the agency and a PageSpeed Insights key.
    google_client_id: str = field(default_factory=lambda: _env("GOOGLE_OAUTH_CLIENT_ID"))
    google_client_secret: str = field(default_factory=lambda: _env("GOOGLE_OAUTH_CLIENT_SECRET"))
    google_redirect_uri: str = field(default_factory=lambda: _env(
        "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/oauth/google/callback"))
    pagespeed_api_key: str = field(default_factory=lambda: _env("GOOGLE_PAGESPEED_API_KEY"))

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


settings = Settings()
