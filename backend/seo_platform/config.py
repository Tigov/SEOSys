"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("SEO_DB_PATH", BACKEND_DIR / "data" / "seo_platform.db")))
    demo_site_url: str = field(default_factory=lambda: os.environ.get("DEMO_SITE_URL", "http://127.0.0.1:8001"))
    demo_site_secret: str = field(default_factory=lambda: os.environ.get("DEMO_SITE_SECRET", "local-dev-secret-change-me"))
    seed_demo_client: bool = field(default_factory=lambda: _bool("SEED_DEMO_CLIENT", True))
    # Crawling local addresses is required for the demo site. In production this is False (SSRF guard).
    allow_private_hosts: bool = field(default_factory=lambda: _bool("ALLOW_PRIVATE_HOSTS", True))
    max_pages: int = field(default_factory=lambda: int(os.environ.get("CRAWL_MAX_PAGES", "50")))
    crawl_user_agent: str = "SEOPlatformBot/0.1 (+http://localhost)"
    # Optional real LLM. Without a key the platform uses a deterministic offline writer.
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("SEO_LLM_MODEL", "claude-haiku-5-5"))
    default_monthly_budget_usd: float = field(default_factory=lambda: float(os.environ.get("CLIENT_MONTHLY_BUDGET_USD", "80")))


settings = Settings()
