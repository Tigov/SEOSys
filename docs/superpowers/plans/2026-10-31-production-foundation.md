# Production Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-user SQLite demo with a production-ready app on localhost: Postgres, accounts, permissions, Stripe billing, public site.

**Architecture:** Postgres 17 and Mailpit in Docker; the FastAPI app on the host. `Database`/`ClientRepo` keep their public methods but run on SQLAlchemy Core with psycopg 3, with row-level security as a second layer. Auth is in-house (argon2id, DB sessions in HttpOnly cookies, CSRF header, TOTP). One permission table drives every route.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 Core, Alembic, psycopg 3, argon2-cffi, pyotp, cryptography, stripe; React 19 + TypeScript built with esbuild.

**Spec:** `docs/superpowers/specs/2026-10-31-production-foundation-design.md`

## Global Constraints

- Windows and PowerShell compatible; `.bat`/`.ps1` keep CRLF. Venv and local data live in `%LOCALAPPDATA%\ProjectSEOSys`.
- Only the seven approved new runtime packages. Ask before any other.
- `cd backend; python -m pytest` green and `cd frontend; npm run typecheck` passing after every task. Every new behaviour has a test.
- UI copy: sentence case, plain English, all through `frontend/src/labels.ts`. Every interactive element gets a `data-testid`.
- No AI attribution anywhere; never stage `AGENTS.md`, `CLAUDE.md`, `notes/`.
- SQL conventions from spec section 4 (identity keys, `timestamptz`, `numeric(12,4)` money, `text` + named `CHECK`, indexed FKs with explicit `ON DELETE`, booleans, parameterised queries).
- No transaction held open across an outside HTTP call.
- Graph first (code-review-graph) before reading code; `code-review-graph update` after edits.

## Review Focus

1. The same Stripe event delivered twice at once must create one client, not two (Task 13: `test_duplicate_webhook_concurrent`).
2. `" Viktor@Example.COM "` at sign-up, login and reset must all mean the same account (Task 7: `test_email_normalised_everywhere`).
3. A session must stop working the moment its user is suspended or resets their password, including requests already holding the cookie (Task 7: `test_suspend_kills_sessions`, `test_reset_ends_other_sessions`).
4. A client must always keep exactly one owner: an owner can't remove or demote themselves without transferring first (Task 11: `test_owner_cannot_leave_without_transfer`).
5. Status gates apply on every path, not only the main button: a past-due client's deploys are refused through `/changes/bulk` too (Task 13: `test_past_due_blocks_bulk_deploy`).

---

## Phase 1: Postgres and the data layer

### Task 1: Docker services, config and dependencies

**Files:**
- Create: `docker-compose.yml`, `ops/postgres/init.sql`
- Modify: `backend/requirements.txt`, `backend/seo_platform/config.py`, `.env.example`, `start.ps1`, `run-tests.ps1`, `.gitattributes` (if `*.sql` needs LF)

**Interfaces:**
- Produces: `settings.database_url` (app role, `postgresql+psycopg://seosys_app:...@localhost:5432/seosys`), `settings.database_owner_url` (owner role, migrations), `settings.app_env` (`development|test|production`), `settings.app_base_url`, `settings.encryption_key`, `settings.encryption_keys_old: tuple[str, ...]`.

- [ ] Compose: `db` = `postgres:17`, port `5432`, volume `seosys-pg`, `POSTGRES_USER=seosys_owner`, healthcheck `pg_isready`; `init.sql` mounted at `/docker-entrypoint-initdb.d/` creates role `seosys_app LOGIN PASSWORD 'seosys_app_local'`, databases `seosys` and `seosys_test` owned by `seosys_owner`, `GRANT CONNECT`. `mail` = `axllent/mailpit`, ports `1025`, `8025`.
- [ ] Requirements add: `sqlalchemy>=2.0`, `alembic>=1.13`, `psycopg[binary]>=3.2`, `argon2-cffi>=23.1`, `pyotp>=2.9`, `cryptography>=43`, `stripe>=11`.
- [ ] `start.ps1`: fail with a plain message if `docker info` fails; `docker compose up -d --wait`; `python -m alembic upgrade head` (owner URL); then start servers. `run-tests.ps1`: same compose step, then pytest.
- [ ] Verify: `docker compose up -d --wait` then `docker compose exec db psql -U seosys_owner -l` lists `seosys` and `seosys_test`.
- [ ] Commit.

### Task 2: Schema and Alembic migration 0001

**Files:**
- Create: `backend/seo_platform/schema.py` (SQLAlchemy `MetaData` + every `Table`), `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/versions/0001_initial.py`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Produces: `schema.metadata`; `schema.CLIENT_TABLES: frozenset[str]` (tables carrying `client_id`, replaces `ALLOWED_TABLES`); `schema.ENCRYPTED: frozenset[tuple[str, str]]` = `{("connections","access_token"), ("connections","refresh_token"), ("sites","adapter_secret"), ("users","totp_secret")}`.

- [ ] Tables per spec section 4 (existing tables converted, plus `users`, `memberships`, `sessions`, `email_tokens`, `invites`, `recovery_codes`, `subscriptions`, `stripe_events`, `login_attempts`, `email_outbox`). Booleans for `auto_approve_low`, `freeze_deploys`, `noindex`, `in_sitemap`, `mentioned`, `acknowledged`.
- [ ] Migration 0001 creates them, grants `SELECT, INSERT, UPDATE, DELETE` on all tables and `USAGE` on sequences to `seosys_app`, then `REVOKE UPDATE, DELETE ON audit_events FROM seosys_app`. Downgrade drops everything.
- [ ] Tests: `test_upgrade_downgrade_upgrade` (runs against `seosys_test`), `test_schema_matches_metadata` (alembic `compare_metadata` returns `[]`), `test_one_owner_per_client` (second owner insert raises `IntegrityError`), `test_email_must_be_lowercase`.
- [ ] Commit.

### Task 3: Port `Database` and `ClientRepo` to Postgres

**Files:**
- Modify: `backend/seo_platform/db.py`, `backend/tests/conftest.py`, call sites using `= 0/1` on boolean columns (`services.py`, `visibility.py`, `api.py`), `ClientRepo.month_spend`
- Test: `backend/tests/test_db.py`; existing `test_pipeline.py`, `test_google.py` must pass

**Interfaces:**
- Produces: `Database(url: str)`; `query/one/execute/insert` unchanged (keep `?` placeholders; translated to bound parameters); `Database.transaction() -> ContextManager` (nested calls on the same thread/task join it); `Database.wipe()` = `TRUNCATE ... RESTART IDENTITY CASCADE`; rows come back with `datetime` as ISO 8601 strings, `Decimal` as `float`, JSON as Python objects. `ClientRepo` methods unchanged; statements run with `app.client_id` set. `Database` methods run with `app.scope='system'`.

- [ ] Tests first in `test_db.py`: `test_placeholders_bind_safely` (value `"x'; DROP TABLE clients;--"` round-trips), `test_transaction_rolls_back`, `test_repo_cannot_read_other_client`, `test_timestamps_are_iso_strings`, `test_money_is_float`.
- [ ] `conftest.py`: session-scoped fixture runs `alembic upgrade head` on `seosys_test`; per-test `db` fixture `wipe()`s; `api` fixture uses it. Skip the whole run with a clear message if Postgres is unreachable.
- [ ] Implement; run full suite: all previous tests pass.
- [ ] Commit.

### Task 4: Field encryption

**Files:**
- Create: `backend/seo_platform/crypto.py`
- Modify: `db.py` (encrypt on write, decrypt on read for `schema.ENCRYPTED`)
- Test: `backend/tests/test_crypto.py`

**Interfaces:**
- Produces: `encrypt(plain: str) -> str` (`"v1:" + base64(nonce+ct)`), `decrypt(token: str) -> str`, `generate_key() -> str`. Key = 32 bytes, urlsafe base64 in `APP_ENCRYPTION_KEY`; older keys in `APP_ENCRYPTION_KEYS_OLD` as `v<n>=<key>` comma list.

- [ ] Tests: `test_round_trip`, `test_tampered_ciphertext_rejected`, `test_old_key_still_decrypts`, `test_tokens_not_plaintext_in_db` (read `connections.refresh_token` with a raw SQL on the owner connection and assert it starts with `v1:`).
- [ ] Commit.

## Phase 2: Accounts

### Task 5: Clock, passwords, tokens

**Files:**
- Create: `backend/seo_platform/clock.py`, `backend/seo_platform/auth/__init__.py`, `auth/passwords.py`, `auth/tokens.py`, `backend/seo_platform/data/common-passwords.txt` (top 100,000 list, MIT-licensed SecLists source noted in a header line)
- Test: `backend/tests/test_passwords.py`

**Interfaces:**
- Produces: `clock.now() -> datetime` (UTC, patchable via `clock.set(dt)` / `clock.reset()` in tests); `db.now()` uses it. `passwords.hash(pw) -> str`, `passwords.verify(hash, pw) -> bool`, `passwords.needs_rehash(hash) -> bool`, `passwords.problem(pw, email) -> str | None` (user-facing reason or None), `passwords.DUMMY_HASH`. `tokens.new() -> str` (32 bytes urlsafe), `tokens.digest(token) -> str` (hex SHA-256).

- [ ] Tests: `test_short_password_rejected` (11 chars), `test_common_password_rejected` (`"password1234"`), `test_contains_email_name_rejected`, `test_129_chars_rejected`, `test_good_password_ok`, `test_verify_wrong_password_false`.
- [ ] Commit.

### Task 6: Email outbox and Mailpit

**Files:**
- Create: `backend/seo_platform/mailer.py`, `backend/seo_platform/email_copy.py`
- Modify: `config.py` (`SMTP_HOST=localhost`, `SMTP_PORT=1025`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS=false`, `MAIL_FROM="SEOSys <no-reply@seosys.local>"`)
- Test: `backend/tests/test_mailer.py`

**Interfaces:**
- Produces: `mailer.queue(db, to_email: str, template: str, **context) -> int` (inserts `email_outbox`, joins the caller's transaction); `mailer.send_pending(db, transport=None) -> int` (sends up to 50, retries with `attempts < 5`); `mailer.Outbox` test helper capturing sent messages. Templates: `verify`, `reset`, `invite`, `welcome`, `already_registered`, `payment_failed`, `mfa_changed`, `new_device`.

- [ ] Tests: `test_rolled_back_action_sends_nothing`, `test_failed_send_retries_then_marks_failed`, `test_every_template_renders_html_and_text`.
- [ ] Commit.

### Task 7: Sign-up, login, sessions, verification, reset

**Files:**
- Create: `auth/service.py` (logic), `auth/sessions.py`, `auth/routes.py` (APIRouter `/api/auth`)
- Modify: `api.py` (include router; `Principal` dependency)
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces: `Principal` dataclass (`user_id: int`, `email`, `name`, `is_admin: bool`, `mfa_passed: bool`, `session_id_hash`, `csrf_token`); dependency `current_principal(request) -> Principal | None`; `require_login` (401 if None). Cookie name `seosys_session`. Routes: `POST /signup {email,name,password}`, `POST /login {email,password}` → `{mfa_required: bool}`, `POST /logout`, `GET /me` → user, memberships, `csrf_token`, `POST /verify {token}`, `POST /verify/resend`, `POST /forgot {email}`, `POST /reset {token,password}`, `POST /password {current,new}`, `GET /sessions`, `DELETE /sessions/{id}`, `PATCH /me {name}`.

- [ ] Tests (values from spec 5): `test_signup_creates_unverified_user_and_queues_verify`, `test_signup_taken_email_same_response_and_emails_owner`, `test_email_normalised_everywhere`, `test_login_unknown_email_generic_error`, `test_lockout_after_5_failures_for_15_minutes` (uses `clock.set`), `test_ip_block_after_20_failures`, `test_session_idle_12h_absolute_30d`, `test_admin_session_absolute_8h`, `test_session_rotates_on_login`, `test_logout_deletes_session`, `test_reset_token_single_use_30_min`, `test_reset_ends_other_sessions`, `test_reset_rate_limit_3_per_hour`, `test_verify_token_24h`, `test_suspend_kills_sessions`, `test_cookie_flags` (HttpOnly, SameSite=Lax; Secure when `APP_ENV=production`), `test_password_rehash_on_login`.
- [ ] Commit.

### Task 8: Two-step login and recovery codes

**Files:**
- Create: `auth/mfa.py`
- Modify: `auth/routes.py`, `auth/sessions.py`
- Test: `backend/tests/test_mfa.py`

**Interfaces:**
- Produces: routes `POST /api/auth/mfa/setup` → `{otpauth_uri}`, `POST /mfa/enable {code}` → `{recovery_codes: [10]}`, `POST /mfa/verify {code}` (marks session `mfa_passed`, rotates session), `POST /mfa/recovery {code}`, `POST /mfa/disable {password|code}`, `POST /mfa/recovery-codes {password}`. Dependency `require_mfa_ok` (admin without `mfa_passed` → 403 `mfa_required`; client member of a `require_mfa` client without TOTP → 403 `mfa_setup_required`).

- [ ] Tests: `test_code_replay_rejected`, `test_window_plus_minus_one_step`, `test_recovery_code_single_use`, `test_admin_blocked_until_mfa`, `test_require_mfa_client_forces_setup`, `test_disable_needs_password_or_code`, `test_mfa_change_emails_user`.
- [ ] Commit.

### Task 9: Sign in with Google

**Files:**
- Modify: `adapters/google.py` (sign-in start/finish using `oauth_states.purpose='signin'`, scopes `openid email profile`), `auth/routes.py`, `api.py` callback dispatch by purpose
- Test: extend `backend/tests/test_google.py`

**Interfaces:**
- Produces: `GET /api/auth/google/start` → redirect; callback creates or signs in a verified user; existing password account with the same email gets a `link_google` email and the callback redirects to `/#/login?google=link_sent`.

- [ ] Tests: `test_google_signin_creates_verified_user`, `test_google_signin_existing_google_user`, `test_google_email_matches_password_account_requires_link`, `test_link_token_links_account`, `test_signin_state_reuse_rejected`.
- [ ] Commit.

## Phase 3: Permissions

### Task 10: Permission table, route enforcement, CSRF

**Files:**
- Create: `backend/seo_platform/permissions.py`
- Modify: `api.py` (remove `Caller`, `X-Role`, `staff_only`; every route gets `Depends(require("<action>"))`), `changes.py` (role argument becomes `Principal`-derived `"staff"`/`"client"` via `permissions.change_role(principal, client_id)`)
- Test: `backend/tests/test_permissions.py`, update `conftest.py` helpers (`login_as(api, who)`), migrate existing tests to sessions

**Interfaces:**
- Produces: `ACTIONS: dict[str, frozenset[Role]]` with roles `admin`, `owner`, `member`, `approver`, `no_package`, `public`; `require(action) -> Depends` that resolves the `client_id` path parameter, the principal's membership, and raises 401/403; `Access` object (principal, client_id, role) injected into handlers; CSRF middleware: non-GET requires `X-CSRF-Token` == session token, exempt `/api/billing/webhook` and OAuth callbacks.

- [ ] Tests: `test_every_route_declares_action` (walks `app.routes`), `test_missing_csrf_rejected`, `test_wrong_csrf_rejected`, `test_x_role_header_ignored`.
- [ ] Commit.

### Task 11: Memberships, invites and team

**Files:**
- Create: `backend/seo_platform/team.py`, routes in `api.py` under `/api/clients/{id}/team`
- Test: `backend/tests/test_team.py`

**Interfaces:**
- Produces: `GET /team`, `POST /team/invites {email, role, can_approve}`, `DELETE /team/invites/{token_hash}`, `POST /api/invites/accept {token}` (signed-in user whose email matches), `PATCH /team/{user_id} {role?, can_approve?}`, `DELETE /team/{user_id}`, `POST /team/transfer {user_id}` (owner → that member, atomic), `PATCH /api/clients/{id}/settings {require_mfa}` (owner).

- [ ] Tests: `test_invite_expires_after_7_days`, `test_invite_email_must_match`, `test_accept_is_atomic_and_single_use`, `test_owner_cannot_leave_without_transfer`, `test_transfer_ownership_swaps_roles`, `test_member_cannot_invite`.
- [ ] Commit.

### Task 12: Row-level security and the permission matrix

**Files:**
- Create: `backend/migrations/versions/0002_row_level_security.py`
- Test: `backend/tests/test_rls.py`, `backend/tests/test_permission_matrix.py`

**Interfaces:**
- Consumes: `permissions.ACTIONS`, route → action map from Task 10.

- [ ] Policies on every `schema.CLIENT_TABLES` table as in spec section 4.
- [ ] Tests: `test_app_role_without_setting_sees_nothing`, `test_app_role_sees_only_its_client`, `test_system_scope_sees_all`. Matrix: parametrise over every route × principals (`admin`, `owner`, `member`, `approver`, `no_package`, `anonymous`, `suspended`, `past_due_owner`, `cancelled_owner`, `other_client_owner`); expected outcome computed from `ACTIONS` plus status rules; assert status code class (2xx/4xx-not-403 vs 401/403/402).
- [ ] Commit.

## Phase 4: Billing

### Task 13: Plans, checkout, webhooks, statuses, maintenance

**Files:**
- Create: `backend/seo_platform/plans.py`, `backend/seo_platform/billing.py`, `backend/seo_platform/maintenance.py`, `backend/seo_platform/__main__.py` (CLI: `seed`, `maintenance`)
- Modify: `config.py` (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_<PLAN>`), `api.py`, `permissions.py` status gates
- Test: `backend/tests/test_billing.py` with `FakeStripe`

**Interfaces:**
- Produces: `plans.PLANS: dict[str, Plan]` (`id`, `name`, `price_env`, `summary`, `includes`), from `notes/Project/Business and Offer.md`; `POST /api/billing/checkout {plan}` → `{url}`; `POST /api/billing/portal` → `{url}`; `POST /api/billing/webhook`; `POST /api/admin/clients/{id}/activate`; `maintenance.run(db) -> dict[str,int]`; status gate `status_allows(client, action) -> bool`.

- [ ] Tests: `test_checkout_requires_verified_email`, `test_checkout_completed_creates_client_owner_subscription_and_welcome`, `test_duplicate_webhook_concurrent` (two threads, same event id → one client), `test_bad_signature_rejected`, `test_payment_failed_sets_past_due_and_emails`, `test_past_due_blocks_bulk_deploy`, `test_cancelled_read_only_30_days_then_closed` (clock), `test_closed_export_window_then_deleted`, `test_manual_activation_logged`, `test_maintenance_idempotent`.
- [ ] Commit.

## Phase 5: Front end

### Task 14: API client, auth state, routing

**Files:**
- Modify: `frontend/src/api.ts` (drop role; `credentials: "same-origin"`; CSRF header from `/api/auth/me`; 401 → login), `App.tsx` (routes: public, account, portal, admin), `main.tsx`
- Create: `frontend/src/auth.tsx` (`AuthProvider`, `useAuth()` → `{me, refresh, logout}`), `frontend/src/can.ts` (mirrors `ACTIONS` from `GET /api/auth/permissions`)

- [ ] `npm run typecheck` and `npm run build` pass; portal loads after login in the browser.
- [ ] Commit.

### Task 15: Public site

Use the frontend-design skill. **Files:** `frontend/src/public/*.tsx` (Home, HowItWorks, Packages, Check, About, Contact, Privacy, Terms), `labels.ts` copy, `styles.css`. Placeholder wordmark "SEOSys".

- [ ] Packages page reads `GET /api/plans`; "Buy" sends signed-out users to sign up, unverified users to verify, others to checkout.
- [ ] Verify in browser at 375 px and 1280 px; commit.

### Task 16: Account pages

**Files:** `frontend/src/account/*.tsx` (SignUp, LogIn, Verify, Forgot, Reset, AcceptInvite, Profile, Password, TwoStep with QR from `otpauth://` drawn by a small inline QR encoder written in-repo, RecoveryCodes, Sessions).

- [ ] Browser check of sign-up → Mailpit link → verify → log in → set up two-step; commit.

### Task 17: Portal by role, team, billing, client switcher

**Files:** modify `pages/*.tsx` to hide actions via `can()`; create `pages/Team.tsx`, `pages/Billing.tsx`, `components/ClientSwitcher.tsx`, past-due banner.

- [ ] Browser check as owner, member, approver; commit.

## Phase 6: Admin and hardening

### Task 18: Admin pages

**Files:** `backend` routes `/api/admin/{clients,users,subscriptions,audit}` and suspend/reactivate; `frontend/src/admin/*.tsx`. Tests in `backend/tests/test_admin.py`: `test_suspend_user`, `test_admin_lists_all_clients`, `test_non_admin_refused`.

### Task 19: Security headers, health, logs, production checks, hashed builds

**Files:** `backend/seo_platform/middleware.py`, `config.py` validation, `frontend/build.mjs` (content-hashed names, `index.html` rewritten), `api.py` (`/healthz`, `/readyz`; remove `/api/health` and demo controls outside development).

- [ ] Tests: `test_security_headers_present`, `test_production_refuses_example_secret`, `test_production_requires_https_base_url`, `test_readyz_reports_db`, `test_logs_never_contain_session_cookie`.
- [ ] Commit.

### Task 20: Seed, scripts, docs, wording

**Files:** `seo_platform/__main__.py seed --demo` (admin from `SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD`, one user per role, clients in each status), `start.ps1`, `README.md`, `ops/production-checklist.md`, `ops/environment.md`, `ops/backup.ps1`, `ops/restore.ps1`, remove "proof of concept"/"PoC" wording across tracked files; update notes (local).

- [ ] `git grep -i -E "proof of concept|\bPoC\b"` returns nothing in tracked files.
- [ ] Full suite and typecheck green; commit.
