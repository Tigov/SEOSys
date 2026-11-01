"""Database schema: the single definition Alembic migrations are checked against.

Conventions (spec section 4): identity keys, timestamptz, numeric money, text + named CHECK for enumerations,
every foreign key indexed with an explicit ON DELETE rule, booleans for flags, jsonb for structured values.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, ForeignKey, Identity, Index, Integer, MetaData, Numeric, Table, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP

metadata = MetaData(naming_convention={
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})

TZ = TIMESTAMP(timezone=True)
MONEY = Numeric(12, 4)


def _id() -> Column:
    return Column("id", BigInteger, Identity(always=True), primary_key=True)


def _created() -> Column:
    return Column("created_at", TZ, nullable=False, server_default=text("now()"))


def _fk(name: str, target: str, ondelete: str, nullable: bool = False) -> Column:
    return Column(name, BigInteger, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


def _text(name: str) -> Column:
    return Column(name, Text, nullable=False, server_default="")


def _json(name: str, empty: str = "[]") -> Column:
    return Column(name, JSONB, nullable=False, server_default=text(f"'{empty}'::jsonb"))


def _flag(name: str) -> Column:
    return Column(name, Boolean, nullable=False, server_default=text("false"))


def _one_of(column: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name or column)


CLIENT_STATUSES = ("active", "past_due", "cancelled", "closed")
CHANGE_STATUSES = ("draft", "blocked_policy", "awaiting_client", "approved", "rejected", "discarded", "deploying",
                   "verifying", "live", "rolled_back", "deploy_failed", "failed")

# ---------- accounts ----------

users = Table(
    "users", metadata, _id(),
    Column("email", Text, nullable=False),
    _text("name"),
    Column("password_hash", Text),
    Column("google_sub", Text),
    Column("email_verified_at", TZ),
    _flag("is_admin"),
    Column("totp_secret", Text),
    Column("totp_enabled_at", TZ),
    Column("totp_last_step", BigInteger),
    Column("password_changed_at", TZ),
    Column("status", Text, nullable=False, server_default="active"),
    _created(),
    Column("last_login_at", TZ),
    CheckConstraint("email = lower(email)", name="email_lowercase"),
    _one_of("status", ("active", "suspended")),
    UniqueConstraint("email"),
    UniqueConstraint("google_sub"),
)

clients = Table(
    "clients", metadata, _id(),
    Column("name", Text, nullable=False),
    _text("city"), _text("region"), _text("phone"), _text("street"), _text("postal_code"),
    _json("services"), _json("competitors"),
    _flag("auto_approve_low"), _flag("freeze_deploys"), _flag("require_mfa"),
    Column("monthly_budget_usd", MONEY, nullable=False, server_default=text("80")),
    Column("status", Text, nullable=False, server_default="active"),
    Column("plan", Text),
    Column("stripe_customer_id", Text),
    Column("cancelled_at", TZ),
    _created(),
    _one_of("status", CLIENT_STATUSES),
    UniqueConstraint("stripe_customer_id"),
)

memberships = Table(
    "memberships", metadata,
    Column("user_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("client_id", BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("role", Text, nullable=False),
    _flag("can_approve"),
    _created(),
    _one_of("role", ("owner", "member")),
    Index("uq_memberships_one_owner", "client_id", unique=True, postgresql_where=text("role = 'owner'")),
)

sessions = Table(
    "sessions", metadata,
    Column("id_hash", Text, primary_key=True),
    _fk("user_id", "users.id", "CASCADE"),
    Column("csrf_token", Text, nullable=False),
    _flag("mfa_passed"),
    _created(),
    Column("last_seen_at", TZ, nullable=False, server_default=text("now()")),
    Column("expires_at", TZ, nullable=False, index=True),
    Column("ip", INET),
    _text("user_agent"),
)

email_tokens = Table(
    "email_tokens", metadata,
    Column("token_hash", Text, primary_key=True),
    _fk("user_id", "users.id", "CASCADE"),
    Column("purpose", Text, nullable=False),
    Column("expires_at", TZ, nullable=False, index=True),
    Column("used_at", TZ),
    _created(),
    _one_of("purpose", ("verify", "reset", "link_google")),
)

invites = Table(
    "invites", metadata, _id(),
    Column("token_hash", Text, nullable=False),
    _fk("client_id", "clients.id", "CASCADE"),
    Column("email", Text, nullable=False),
    Column("role", Text, nullable=False),
    _flag("can_approve"),
    _fk("invited_by", "users.id", "SET NULL", nullable=True),
    Column("expires_at", TZ, nullable=False),
    Column("accepted_at", TZ),
    _created(),
    CheckConstraint("email = lower(email)", name="email_lowercase"),
    _one_of("role", ("member",)),
    UniqueConstraint("token_hash"),
)

recovery_codes = Table(
    "recovery_codes", metadata, _id(),
    _fk("user_id", "users.id", "CASCADE"),
    Column("code_hash", Text, nullable=False),
    Column("used_at", TZ),
    _created(),
    UniqueConstraint("user_id", "code_hash"),
)

login_attempts = Table(
    "login_attempts", metadata, _id(),
    Column("ip", INET),
    Column("email", Text, nullable=False),
    Column("kind", Text, nullable=False, server_default="login"),
    Column("ok", Boolean, nullable=False),
    Column("at", TZ, nullable=False, server_default=text("now()")),
    _one_of("kind", ("login", "mfa", "reset", "verify")),
    Index("ix_login_attempts_email_at", "email", "at"),
    Index("ix_login_attempts_ip_at", "ip", "at"),
)

email_outbox = Table(
    "email_outbox", metadata, _id(),
    Column("to_email", Text, nullable=False),
    Column("template", Text, nullable=False),
    _json("context", "{}"),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("next_attempt_at", TZ, nullable=False, server_default=text("now()")),
    Column("last_error", Text),
    _created(),
    Column("sent_at", TZ),
    _one_of("status", ("pending", "sent", "failed")),
    Index("ix_email_outbox_pending", "next_attempt_at", postgresql_where=text("status = 'pending'")),
)

# ---------- billing ----------

subscriptions = Table(
    "subscriptions", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    Column("stripe_subscription_id", Text, nullable=False),
    Column("plan", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("current_period_end", TZ),
    Column("cancel_at", TZ),
    Column("updated_at", TZ, nullable=False, server_default=text("now()")),
    UniqueConstraint("client_id"),
    UniqueConstraint("stripe_subscription_id"),
)

stripe_events = Table(
    "stripe_events", metadata,
    Column("id", Text, primary_key=True),
    Column("type", Text, nullable=False),
    Column("received_at", TZ, nullable=False, server_default=text("now()")),
)

# ---------- client work ----------

sites = Table(
    "sites", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    Column("base_url", Text, nullable=False),
    Column("cms", Text, nullable=False),
    Column("adapter_secret", Text),
    _created(),
    _one_of("cms", ("wordpress", "shopify", "github", "other")),
)

leads = Table(
    "leads", metadata, _id(),
    Column("url", Text, nullable=False),
    Column("email", Text),
    Column("business_name", Text),
    Column("city", Text),
    Column("score", Integer),
    _json("result", "{}"),
    _fk("user_id", "users.id", "SET NULL", nullable=True),
    _created(),
)

crawls = Table(
    "crawls", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    _fk("site_id", "sites.id", "CASCADE", nullable=True),
    Column("kind", Text, nullable=False),
    Column("started_at", TZ, nullable=False, server_default=text("now()")),
    Column("finished_at", TZ),
    Column("pages_crawled", Integer),
    Column("health_score", Integer),
    Column("robots_txt", Text),
    _json("ai_bots_blocked"), _json("sitemap_urls"),
    Index("ix_crawls_client_kind", "client_id", "kind", "id"),
)

pages = Table(
    "pages", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    Column("crawl_id", BigInteger, ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    Column("url", Text), Column("path", Text), Column("status", Integer), Column("final_url", Text),
    _json("redirect_chain"),
    Column("title", Text), Column("meta_description", Text),
    _json("h1s"),
    Column("canonical", Text),
    Column("noindex", Boolean),
    Column("word_count", Integer),
    _json("images"), _json("links"), _json("jsonld_types"),
    Column("in_sitemap", Boolean),
    Index("ix_pages_crawl_id", "crawl_id"),
)

findings = Table(
    "findings", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    _fk("crawl_id", "crawls.id", "SET NULL", nullable=True),
    Column("fingerprint", Text, nullable=False),
    Column("rule_id", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("title", Text, nullable=False),
    _json("urls"), _json("evidence", "{}"),
    Column("effort", Text), Column("impact", Integer), Column("fix_hint", Text), Column("fix_type", Text),
    Column("status", Text, nullable=False, server_default="open"),
    Column("first_seen", TZ, nullable=False, server_default=text("now()")),
    Column("last_seen", TZ, nullable=False, server_default=text("now()")),
    Column("resolved_at", TZ),
    _one_of("severity", ("critical", "high", "medium", "low")),
    _one_of("status", ("open", "fix_deployed", "resolved")),
    Index("ix_findings_client_status", "client_id", "status"),
)

change_requests = Table(
    "change_requests", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    _fk("site_id", "sites.id", "CASCADE"),
    _fk("finding_id", "findings.id", "SET NULL", nullable=True),
    Column("type", Text, nullable=False),
    _json("target", "{}"),
    Column("before_value", Text), Column("after_value", Text),
    Column("risk", Text, nullable=False),
    Column("status", Text, nullable=False),
    _text("reason"),
    Column("author", Text), Column("approved_by", Text),
    Column("deploy_result", JSONB), Column("verification", JSONB),
    _json("policy_flags"),
    _created(),
    Column("updated_at", TZ, nullable=False, server_default=text("now()")),
    _one_of("risk", ("low", "medium", "high")),
    _one_of("status", CHANGE_STATUSES),
    Index("ix_change_requests_client_status", "client_id", "status"),
)

audit_events = Table(
    "audit_events", metadata, _id(),
    _fk("client_id", "clients.id", "SET NULL", nullable=True),
    _fk("actor_user_id", "users.id", "SET NULL", nullable=True),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    _text("target"),
    _json("detail", "{}"),
    Column("ip", INET),
    _text("user_agent"),
    Column("at", TZ, nullable=False, server_default=text("now()")),
)

usage_events = Table(
    "usage_events", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE", nullable=True),
    Column("vendor", Text, nullable=False),
    Column("unit", Text, nullable=False),
    Column("qty", Numeric(14, 4), nullable=False),
    Column("cost_usd", MONEY, nullable=False),
    Column("at", TZ, nullable=False, server_default=text("now()")),
    Index("ix_usage_events_client_at", "client_id", "at"),
)

prompts = Table(
    "prompts", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    Column("text", Text, nullable=False),
    Column("cluster", Text),
    _created(),
)

ai_observations = Table(
    "ai_observations", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    _fk("prompt_id", "prompts.id", "CASCADE", nullable=True),
    Column("run_no", Integer, nullable=False),
    Column("engine", Text, nullable=False),
    Column("method", Text),
    Column("run_at", TZ, nullable=False, server_default=text("now()")),
    _flag("mentioned"),
    Column("position", Integer),
    Column("cited_url", Text),
    _json("brands"), _json("sources"),
    Column("answer", Text),
    Index("ix_ai_observations_client_run", "client_id", "run_no"),
)

alerts = Table(
    "alerts", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE", nullable=True),
    Column("level", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("at", TZ, nullable=False, server_default=text("now()")),
    _flag("acknowledged"),
)

connections = Table(
    "connections", metadata, _id(),
    _fk("client_id", "clients.id", "CASCADE"),
    Column("provider", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="not_connected"),
    Column("account_email", Text),
    _json("scopes"),
    Column("access_token", Text), Column("refresh_token", Text),
    Column("expires_at", TZ),
    Column("gsc_site", Text), Column("ga4_property", Text),
    _created(),
    Column("updated_at", TZ, nullable=False, server_default=text("now()")),
    _one_of("status", ("connected", "expired", "not_connected")),
    UniqueConstraint("client_id", "provider"),
)

oauth_states = Table(
    "oauth_states", metadata,
    Column("state", Text, primary_key=True),
    Column("purpose", Text, nullable=False, server_default="connect"),
    _fk("client_id", "clients.id", "CASCADE", nullable=True),
    _fk("user_id", "users.id", "CASCADE", nullable=True),
    Column("provider", Text, nullable=False),
    _text("actor"),
    Column("code_verifier", Text, nullable=False),
    _created(),
    _one_of("purpose", ("connect", "signin")),
)

# Tables that carry client_id and are reached through ClientRepo. Row-level security applies to these.
CLIENT_TABLES = frozenset({
    "sites", "crawls", "pages", "findings", "change_requests", "audit_events", "usage_events", "prompts",
    "ai_observations", "alerts", "connections",
})

# Columns encrypted at rest. db.py encrypts on write and decrypts on read.
ENCRYPTED = frozenset({
    ("connections", "access_token"), ("connections", "refresh_token"), ("sites", "adapter_secret"),
    ("users", "totp_secret"),
})

JSON_COLUMNS = frozenset((t.name, c.name) for t in metadata.tables.values() for c in t.columns if isinstance(c.type, JSONB))
