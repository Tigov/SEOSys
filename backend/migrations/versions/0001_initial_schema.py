"""Initial schema: accounts, billing and client work.

Revision ID: 0001
Revises: 
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('clients',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('city', sa.Text(), server_default='', nullable=False),
    sa.Column('region', sa.Text(), server_default='', nullable=False),
    sa.Column('phone', sa.Text(), server_default='', nullable=False),
    sa.Column('street', sa.Text(), server_default='', nullable=False),
    sa.Column('postal_code', sa.Text(), server_default='', nullable=False),
    sa.Column('services', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('competitors', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('auto_approve_low', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('freeze_deploys', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('require_mfa', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('monthly_budget_usd', sa.Numeric(precision=12, scale=4), server_default=sa.text('80'), nullable=False),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('plan', sa.Text(), nullable=True),
    sa.Column('stripe_customer_id', sa.Text(), nullable=True),
    sa.Column('cancelled_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'past_due', 'cancelled', 'closed')", name=op.f('ck_clients_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clients')),
    sa.UniqueConstraint('stripe_customer_id', name=op.f('uq_clients_stripe_customer_id'))
    )
    op.create_table('email_outbox',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('to_email', sa.Text(), nullable=False),
    sa.Column('template', sa.Text(), nullable=False),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('next_attempt_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name=op.f('ck_email_outbox_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_outbox'))
    )
    op.create_index('ix_email_outbox_pending', 'email_outbox', ['next_attempt_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_table('login_attempts',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), server_default='login', nullable=False),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('login', 'mfa', 'reset', 'verify')", name=op.f('ck_login_attempts_kind')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts'))
    )
    op.create_index('ix_login_attempts_email_at', 'login_attempts', ['email', 'at'], unique=False)
    op.create_index('ix_login_attempts_ip_at', 'login_attempts', ['ip', 'at'], unique=False)
    op.create_table('stripe_events',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('received_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stripe_events'))
    )
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), server_default='', nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('google_sub', sa.Text(), nullable=True),
    sa.Column('email_verified_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('totp_secret', sa.Text(), nullable=True),
    sa.Column('totp_enabled_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('totp_last_step', sa.BigInteger(), nullable=True),
    sa.Column('password_changed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('active', 'suspended')", name=op.f('ck_users_status')),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_users_email_lowercase')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('google_sub', name=op.f('uq_users_google_sub'))
    )
    op.create_table('alerts',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=True),
    sa.Column('level', sa.Text(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('acknowledged', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_alerts_client_id_clients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts'))
    )
    op.create_index(op.f('ix_alerts_client_id'), 'alerts', ['client_id'], unique=False)
    op.create_table('audit_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=True),
    sa.Column('actor_user_id', sa.BigInteger(), nullable=True),
    sa.Column('actor', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('target', sa.Text(), server_default='', nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.Text(), server_default='', nullable=False),
    sa.Column('at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_events_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_audit_events_client_id_clients'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_actor_user_id'), 'audit_events', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_audit_events_client_id'), 'audit_events', ['client_id'], unique=False)
    op.create_table('connections',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='not_connected', nullable=False),
    sa.Column('account_email', sa.Text(), nullable=True),
    sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('access_token', sa.Text(), nullable=True),
    sa.Column('refresh_token', sa.Text(), nullable=True),
    sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('gsc_site', sa.Text(), nullable=True),
    sa.Column('ga4_property', sa.Text(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('connected', 'expired', 'not_connected')", name=op.f('ck_connections_status')),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_connections_client_id_clients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_connections')),
    sa.UniqueConstraint('client_id', 'provider', name=op.f('uq_connections_client_id_provider'))
    )
    op.create_index(op.f('ix_connections_client_id'), 'connections', ['client_id'], unique=False)
    op.create_table('email_tokens',
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('used_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("purpose IN ('verify', 'reset', 'link_google')", name=op.f('ck_email_tokens_purpose')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash', name=op.f('pk_email_tokens'))
    )
    op.create_index(op.f('ix_email_tokens_expires_at'), 'email_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_email_tokens_user_id'), 'email_tokens', ['user_id'], unique=False)
    op.create_table('invites',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('can_approve', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('invited_by', sa.BigInteger(), nullable=True),
    sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('accepted_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('member')", name=op.f('ck_invites_role')),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_invites_email_lowercase')),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_invites_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_invites_invited_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invites')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_invites_token_hash'))
    )
    op.create_index(op.f('ix_invites_client_id'), 'invites', ['client_id'], unique=False)
    op.create_index(op.f('ix_invites_invited_by'), 'invites', ['invited_by'], unique=False)
    op.create_table('leads',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('business_name', sa.Text(), nullable=True),
    sa.Column('city', sa.Text(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_leads_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leads'))
    )
    op.create_index(op.f('ix_leads_user_id'), 'leads', ['user_id'], unique=False)
    op.create_table('memberships',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('can_approve', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('owner', 'member')", name=op.f('ck_memberships_role')),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_memberships_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'client_id', name=op.f('pk_memberships'))
    )
    op.create_index(op.f('ix_memberships_client_id'), 'memberships', ['client_id'], unique=False)
    op.create_index('uq_memberships_one_owner', 'memberships', ['client_id'], unique=True, postgresql_where=sa.text("role = 'owner'"))
    op.create_table('oauth_states',
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('purpose', sa.Text(), server_default='connect', nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=True),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('actor', sa.Text(), server_default='', nullable=False),
    sa.Column('code_verifier', sa.Text(), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("purpose IN ('connect', 'signin')", name=op.f('ck_oauth_states_purpose')),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_oauth_states_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_oauth_states_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('state', name=op.f('pk_oauth_states'))
    )
    op.create_index(op.f('ix_oauth_states_client_id'), 'oauth_states', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth_states_user_id'), 'oauth_states', ['user_id'], unique=False)
    op.create_table('prompts',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('cluster', sa.Text(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_prompts_client_id_clients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prompts'))
    )
    op.create_index(op.f('ix_prompts_client_id'), 'prompts', ['client_id'], unique=False)
    op.create_table('recovery_codes',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('code_hash', sa.Text(), nullable=False),
    sa.Column('used_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_recovery_codes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recovery_codes')),
    sa.UniqueConstraint('user_id', 'code_hash', name=op.f('uq_recovery_codes_user_id_code_hash'))
    )
    op.create_index(op.f('ix_recovery_codes_user_id'), 'recovery_codes', ['user_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id_hash', sa.Text(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('csrf_token', sa.Text(), nullable=False),
    sa.Column('mfa_passed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.Text(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id_hash', name=op.f('pk_sessions'))
    )
    op.create_index(op.f('ix_sessions_expires_at'), 'sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('sites',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('base_url', sa.Text(), nullable=False),
    sa.Column('cms', sa.Text(), nullable=False),
    sa.Column('adapter_secret', sa.Text(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("cms IN ('wordpress', 'shopify', 'github', 'other')", name=op.f('ck_sites_cms')),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_sites_client_id_clients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sites'))
    )
    op.create_index(op.f('ix_sites_client_id'), 'sites', ['client_id'], unique=False)
    op.create_table('subscriptions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('stripe_subscription_id', sa.Text(), nullable=False),
    sa.Column('plan', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('current_period_end', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('cancel_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_subscriptions_client_id_clients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
    sa.UniqueConstraint('client_id', name=op.f('uq_subscriptions_client_id')),
    sa.UniqueConstraint('stripe_subscription_id', name=op.f('uq_subscriptions_stripe_subscription_id'))
    )
    op.create_index(op.f('ix_subscriptions_client_id'), 'subscriptions', ['client_id'], unique=False)
    op.create_table('usage_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=True),
    sa.Column('vendor', sa.Text(), nullable=False),
    sa.Column('unit', sa.Text(), nullable=False),
    sa.Column('qty', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_usage_events_client_id_clients'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_events'))
    )
    op.create_index('ix_usage_events_client_at', 'usage_events', ['client_id', 'at'], unique=False)
    op.create_index(op.f('ix_usage_events_client_id'), 'usage_events', ['client_id'], unique=False)
    op.create_table('ai_observations',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('prompt_id', sa.BigInteger(), nullable=True),
    sa.Column('run_no', sa.Integer(), nullable=False),
    sa.Column('engine', sa.Text(), nullable=False),
    sa.Column('method', sa.Text(), nullable=True),
    sa.Column('run_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('mentioned', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('position', sa.Integer(), nullable=True),
    sa.Column('cited_url', sa.Text(), nullable=True),
    sa.Column('brands', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_ai_observations_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prompt_id'], ['prompts.id'], name=op.f('fk_ai_observations_prompt_id_prompts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_observations'))
    )
    op.create_index(op.f('ix_ai_observations_client_id'), 'ai_observations', ['client_id'], unique=False)
    op.create_index('ix_ai_observations_client_run', 'ai_observations', ['client_id', 'run_no'], unique=False)
    op.create_index(op.f('ix_ai_observations_prompt_id'), 'ai_observations', ['prompt_id'], unique=False)
    op.create_table('crawls',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('site_id', sa.BigInteger(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('pages_crawled', sa.Integer(), nullable=True),
    sa.Column('health_score', sa.Integer(), nullable=True),
    sa.Column('robots_txt', sa.Text(), nullable=True),
    sa.Column('ai_bots_blocked', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('sitemap_urls', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_crawls_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_crawls_site_id_sites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crawls'))
    )
    op.create_index(op.f('ix_crawls_client_id'), 'crawls', ['client_id'], unique=False)
    op.create_index('ix_crawls_client_kind', 'crawls', ['client_id', 'kind', 'id'], unique=False)
    op.create_index(op.f('ix_crawls_site_id'), 'crawls', ['site_id'], unique=False)
    op.create_table('findings',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('crawl_id', sa.BigInteger(), nullable=True),
    sa.Column('fingerprint', sa.Text(), nullable=False),
    sa.Column('rule_id', sa.Text(), nullable=False),
    sa.Column('severity', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('urls', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('effort', sa.Text(), nullable=True),
    sa.Column('impact', sa.Integer(), nullable=True),
    sa.Column('fix_hint', sa.Text(), nullable=True),
    sa.Column('fix_type', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='open', nullable=False),
    sa.Column('first_seen', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("severity IN ('critical', 'high', 'medium', 'low')", name=op.f('ck_findings_severity')),
    sa.CheckConstraint("status IN ('open', 'fix_deployed', 'resolved')", name=op.f('ck_findings_status')),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_findings_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crawl_id'], ['crawls.id'], name=op.f('fk_findings_crawl_id_crawls'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_findings'))
    )
    op.create_index(op.f('ix_findings_client_id'), 'findings', ['client_id'], unique=False)
    op.create_index('ix_findings_client_status', 'findings', ['client_id', 'status'], unique=False)
    op.create_index(op.f('ix_findings_crawl_id'), 'findings', ['crawl_id'], unique=False)
    op.create_table('pages',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('crawl_id', sa.BigInteger(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('path', sa.Text(), nullable=True),
    sa.Column('status', sa.Integer(), nullable=True),
    sa.Column('final_url', sa.Text(), nullable=True),
    sa.Column('redirect_chain', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('meta_description', sa.Text(), nullable=True),
    sa.Column('h1s', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('canonical', sa.Text(), nullable=True),
    sa.Column('noindex', sa.Boolean(), nullable=True),
    sa.Column('word_count', sa.Integer(), nullable=True),
    sa.Column('images', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('links', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('jsonld_types', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('in_sitemap', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_pages_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crawl_id'], ['crawls.id'], name=op.f('fk_pages_crawl_id_crawls'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pages'))
    )
    op.create_index(op.f('ix_pages_client_id'), 'pages', ['client_id'], unique=False)
    op.create_index('ix_pages_crawl_id', 'pages', ['crawl_id'], unique=False)
    op.create_table('change_requests',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('site_id', sa.BigInteger(), nullable=False),
    sa.Column('finding_id', sa.BigInteger(), nullable=True),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('target', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('before_value', sa.Text(), nullable=True),
    sa.Column('after_value', sa.Text(), nullable=True),
    sa.Column('risk', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), server_default='', nullable=False),
    sa.Column('author', sa.Text(), nullable=True),
    sa.Column('approved_by', sa.Text(), nullable=True),
    sa.Column('deploy_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('verification', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('policy_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("risk IN ('low', 'medium', 'high')", name=op.f('ck_change_requests_risk')),
    sa.CheckConstraint("status IN ('draft', 'blocked_policy', 'awaiting_client', 'approved', 'rejected', 'discarded', 'deploying', 'verifying', 'live', 'rolled_back', 'deploy_failed', 'failed')", name=op.f('ck_change_requests_status')),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name=op.f('fk_change_requests_client_id_clients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], name=op.f('fk_change_requests_finding_id_findings'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_change_requests_site_id_sites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_change_requests'))
    )
    op.create_index(op.f('ix_change_requests_client_id'), 'change_requests', ['client_id'], unique=False)
    op.create_index('ix_change_requests_client_status', 'change_requests', ['client_id', 'status'], unique=False)
    op.create_index(op.f('ix_change_requests_finding_id'), 'change_requests', ['finding_id'], unique=False)
    op.create_index(op.f('ix_change_requests_site_id'), 'change_requests', ['site_id'], unique=False)

    # The app role reads and writes rows but owns nothing, so row-level security applies to it.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO seosys_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO seosys_app")
    # The audit log is append-only for the app.
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM seosys_app")
    op.execute("REVOKE ALL ON alembic_version FROM seosys_app")

def downgrade() -> None:
    op.drop_index(op.f('ix_change_requests_site_id'), table_name='change_requests')
    op.drop_index(op.f('ix_change_requests_finding_id'), table_name='change_requests')
    op.drop_index('ix_change_requests_client_status', table_name='change_requests')
    op.drop_index(op.f('ix_change_requests_client_id'), table_name='change_requests')
    op.drop_table('change_requests')
    op.drop_index('ix_pages_crawl_id', table_name='pages')
    op.drop_index(op.f('ix_pages_client_id'), table_name='pages')
    op.drop_table('pages')
    op.drop_index(op.f('ix_findings_crawl_id'), table_name='findings')
    op.drop_index('ix_findings_client_status', table_name='findings')
    op.drop_index(op.f('ix_findings_client_id'), table_name='findings')
    op.drop_table('findings')
    op.drop_index(op.f('ix_crawls_site_id'), table_name='crawls')
    op.drop_index('ix_crawls_client_kind', table_name='crawls')
    op.drop_index(op.f('ix_crawls_client_id'), table_name='crawls')
    op.drop_table('crawls')
    op.drop_index(op.f('ix_ai_observations_prompt_id'), table_name='ai_observations')
    op.drop_index('ix_ai_observations_client_run', table_name='ai_observations')
    op.drop_index(op.f('ix_ai_observations_client_id'), table_name='ai_observations')
    op.drop_table('ai_observations')
    op.drop_index(op.f('ix_usage_events_client_id'), table_name='usage_events')
    op.drop_index('ix_usage_events_client_at', table_name='usage_events')
    op.drop_table('usage_events')
    op.drop_index(op.f('ix_subscriptions_client_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_sites_client_id'), table_name='sites')
    op.drop_table('sites')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_expires_at'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_recovery_codes_user_id'), table_name='recovery_codes')
    op.drop_table('recovery_codes')
    op.drop_index(op.f('ix_prompts_client_id'), table_name='prompts')
    op.drop_table('prompts')
    op.drop_index(op.f('ix_oauth_states_user_id'), table_name='oauth_states')
    op.drop_index(op.f('ix_oauth_states_client_id'), table_name='oauth_states')
    op.drop_table('oauth_states')
    op.drop_index('uq_memberships_one_owner', table_name='memberships', postgresql_where=sa.text("role = 'owner'"))
    op.drop_index(op.f('ix_memberships_client_id'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_index(op.f('ix_leads_user_id'), table_name='leads')
    op.drop_table('leads')
    op.drop_index(op.f('ix_invites_invited_by'), table_name='invites')
    op.drop_index(op.f('ix_invites_client_id'), table_name='invites')
    op.drop_table('invites')
    op.drop_index(op.f('ix_email_tokens_user_id'), table_name='email_tokens')
    op.drop_index(op.f('ix_email_tokens_expires_at'), table_name='email_tokens')
    op.drop_table('email_tokens')
    op.drop_index(op.f('ix_connections_client_id'), table_name='connections')
    op.drop_table('connections')
    op.drop_index(op.f('ix_audit_events_client_id'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_actor_user_id'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index(op.f('ix_alerts_client_id'), table_name='alerts')
    op.drop_table('alerts')
    op.drop_table('users')
    op.drop_table('stripe_events')
    op.drop_index('ix_login_attempts_ip_at', table_name='login_attempts')
    op.drop_index('ix_login_attempts_email_at', table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_index('ix_email_outbox_pending', table_name='email_outbox', postgresql_where=sa.text("status = 'pending'"))
    op.drop_table('email_outbox')
    op.drop_table('clients')
