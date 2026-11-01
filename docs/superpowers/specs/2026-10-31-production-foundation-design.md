# Production foundation: database, accounts, permissions, billing

Status: draft for review · Date: 2026-10-31 · Sub-project 1 of 4

## 1. Goal

Turn SEOSys from a single-user demo into the production application, running on localhost. When this
sub-project is done, moving to a hosted environment (AWS or similar) means only changing configuration:
the database URL, secrets, the email provider and live Stripe keys. No code changes.

Later sub-projects, each with its own spec: (2) a test website on GitHub Pages with Search Console and
Analytics, (3) a local WordPress site and the real plugin, (4) real AI-engine adapters and DataForSEO.

## 2. Decisions

| # | Decision | Choice |
|---|---|---|
| P1 | Roles | One **admin** (the founder). Client companies have an **owner** and **members**. The owner can give a member **can approve**. |
| P2 | Sign-in | Email and password, or Google. Two-step login (TOTP) is required for the admin and optional for clients; an owner can require it for their team. |
| P3 | Getting an account | Anyone can sign up. A signed-in user without a package sees what the public sees, plus their profile. Buying a package creates their client company, with them as owner. |
| P4 | Payment | Stripe Checkout and subscriptions, in test mode for local development. |
| P5 | Data layer | Postgres 17 in Docker, SQLAlchemy 2 Core, Alembic, psycopg 3. Postgres row-level security as a second layer. |
| P6 | Auth implementation | Built in-house: argon2id, database-backed sessions in HttpOnly cookies, CSRF tokens, pyotp, field encryption with `cryptography`. |
| P7 | Browser tests | Playwright, added in a later step (asked separately). API-level permission matrix covers every role × endpoint. |

New runtime dependencies (approved 2026-10-31): `sqlalchemy`, `alembic`, `psycopg[binary]`,
`argon2-cffi`, `pyotp`, `cryptography`, `stripe`.

## 3. Local services

`docker-compose.yml` at the repo root:

- `db`: `postgres:17`, port 5432, named volume, databases `seosys` and `seosys_test`.
- `mail`: `axllent/mailpit`, SMTP on 1025, web inbox on http://localhost:8025.

The app itself runs on the host through `start.bat` (unchanged entry point) so it can be debugged on
Windows. `start.bat` checks Docker is running, runs `docker compose up -d`, applies migrations, then
starts the server.

## 4. Data model

### SQL conventions

- Table names are plural snake_case; every table has a primary key. Surrogate keys are
  `bigint GENERATED ALWAYS AS IDENTITY`.
- Every timestamp is `timestamptz NOT NULL DEFAULT now()` unless it marks an optional event
  (`used_at`, `verified_at`), which is nullable. The API returns ISO 8601 UTC strings.
- Money is `numeric(12,4)`, never floating point (`usage_events.cost_usd`, `clients.monthly_budget_usd`).
- Enumerated values are `text` with a named `CHECK` constraint (easier to change in a migration than a
  Postgres enum).
- Every foreign key is declared with an explicit `ON DELETE` rule (`CASCADE` for rows owned by their
  parent, `RESTRICT` otherwise) and has an index, since Postgres does not index foreign keys itself.
- Emails are stored lower-cased with `CHECK (email = lower(email))` and a unique index.
- Constraints carry business rules where the database can enforce them: one owner per client is a
  partial unique index `ON memberships (client_id) WHERE role = 'owner'`; a subscription per client is
  `UNIQUE (client_id)`.
- All queries are parameterised through SQLAlchemy Core. No string-built SQL except identifiers from a
  fixed allow-list.
- Single statements commit on their own. Multi-step writes (sign-up, checkout completion, invite
  acceptance, ownership transfer, password reset) run inside an explicit `db.transaction()` block and are
  atomic. No transaction is held open across a call to an outside service (Google, Stripe, a client's
  website), so a slow site never holds database locks. Idempotency inserts use `ON CONFLICT DO NOTHING`
  inside the same transaction as their effects.
- Boolean flags are `boolean`, not integers.
- Connection pooling via the SQLAlchemy engine (`pool_pre_ping`, sized from env). The app connects as
  `seosys_app`, which owns no tables and has only `SELECT/INSERT/UPDATE/DELETE`; `audit_events` is
  append-only (no `UPDATE`/`DELETE` granted). Migrations run as the owner role `seosys_owner`.
- Each migration has a working downgrade, and a test checks that the migrated schema matches the
  SQLAlchemy metadata.

### Secrets at rest

Values marked *hash* are stored as SHA-256 of a high-entropy random value (session IDs, email tokens,
invites, recovery codes). Passwords use argon2id (library defaults, rehashed on login when the
parameters change). Values marked *enc* use AES-256-GCM via `cryptography` with `APP_ENCRYPTION_KEY`;
the stored value is `v<key version>:<nonce+ciphertext, base64>` so keys can rotate
(`APP_ENCRYPTION_KEYS_OLD` holds previous keys for decryption only).

### New tables

**users**: `id`, `email` (unique, lower-cased), `name`, `password_hash` (nullable: Google-only users),
`google_sub` (unique, nullable), `email_verified_at`, `is_admin` (bool, default false), `totp_secret`
(*enc*, nullable), `totp_enabled_at`, `totp_last_step` (bigint, blocks reusing a code),
`failed_logins` (int), `locked_until`, `password_changed_at`, `status`
(`active` | `suspended`), `created_at`, `last_login_at`.

**memberships**: `user_id`, `client_id`, `role` (`owner` | `member`), `can_approve` (bool),
`created_at`. Primary key (`user_id`, `client_id`). Each client has exactly one owner at a time.

**sessions**: `id_hash` (PK, *hash* of the cookie value), `user_id`, `csrf_token`, `mfa_passed` (bool),
`created_at`, `last_seen_at`, `expires_at`, `ip`, `user_agent`.

**email_tokens**: `token_hash` (PK), `user_id`, `purpose` (`verify` | `reset` | `link_google`),
`expires_at`, `used_at`.

**invites**: `token_hash` (PK), `client_id`, `email`, `role`, `can_approve`, `invited_by`,
`expires_at` (7 days), `accepted_at`.

**recovery_codes**: `user_id`, `code_hash`, `used_at`. Ten per user, regenerated as a set.

**subscriptions**: `client_id` (unique), `stripe_subscription_id`, `plan`, `status` (Stripe's status),
`current_period_end`, `cancel_at`, `updated_at`.

**stripe_events**: `id` (Stripe event id, PK), `type`, `received_at`. Used to ignore duplicate webhooks.

**login_attempts**: `id`, `ip` (`inet`), `email`, `at`, `ok`. Indexed on (`email`, `at`) and
(`ip`, `at`). Rate limiting and lockout; rows older than 24 hours are deleted by the maintenance job.

**email_outbox**: `id`, `to_email`, `template`, `context` (jsonb), `status` (`pending` | `sent` |
`failed`), `attempts`, `last_error`, `created_at`, `sent_at`. Emails are written in the same
transaction as the action that causes them and sent by a background loop, so a rolled-back action never
sends mail and a mail outage never loses one.

### Changed tables

- **clients**: add `status` (`active` | `past_due` | `cancelled` | `closed`), `plan`,
  `stripe_customer_id`, `require_mfa` (bool), `cancelled_at`.
- **sites**: `adapter_secret` becomes *enc*.
- **connections**: `access_token`, `refresh_token` become *enc*.
- **audit_events**: `actor` becomes `actor_user_id` (nullable, for the system) plus `actor_label`; add
  `ip`, `user_agent`.
- **oauth_states**: add `purpose` (`connect` | `signin`); `client_id` becomes nullable (sign-in has no
  client yet).
- **leads**: add `user_id` (nullable) so a free check run while signed in is linked to the account.
- All JSON columns become `jsonb`.

### Row-level security

Every client-owned table has a policy
`client_id = nullif(current_setting('app.client_id', true), '')::bigint`, or the system bypass
`current_setting('app.scope', true) = 'system'`. The app connects as a non-owner role `seosys_app` so
policies apply. `ClientRepo` runs every statement with `app.client_id` set (transaction-local
`set_config(..., true)`) and no system scope; agency-level code in `Database` (admin pages, the
maintenance job, webhooks) runs with `app.scope = 'system'`. With neither setting, a query sees no
client rows, so a missing setting fails closed. Code-level filtering by `client_id` stays as the first
layer.

## 5. Accounts and sessions

### Sign-up and sign-in

- **Passwords**: 12 to 128 characters, rejected if found in a bundled list of 100,000 common passwords
  or if they contain the email's local part. No composition rules (NIST SP 800-63B).
- **Email verification**: a link valid for 24 hours. Required before buying a package. Google sign-in
  counts as verified.
- **Google sign-in**: the same OAuth client as the connector, scopes `openid email profile` only. If the
  Google email matches an existing password account, the accounts are linked only after the user proves
  ownership (password login, or a `link_google` email link).
- **Errors**: login, sign-up and reset never reveal whether an email is registered. Reset always says
  "If that email has an account, we've sent a link." Sign-up with a taken email sends that address a
  "you already have an account" email instead of an error. Login with an unknown email still runs an
  argon2 verification against a dummy hash, so timing doesn't reveal it either.

### Two-step login

- TOTP (RFC 6238, 30 s, 6 digits, ±1 step), set up with a QR code and confirmed with a first code.
  A code's time step must be newer than `totp_last_step`, so a code can't be replayed. The QR code is
  drawn in the browser from the `otpauth://` URI (no image library on the server).
- Ten one-time recovery codes, shown once.
- Required for the admin: an admin session without `mfa_passed` can only reach the two-step pages.
- Optional for clients; when the client's `require_mfa` is on, members without TOTP are sent to set it up.
- Turning two-step off, or regenerating recovery codes, needs the current password or a code.

### Lockout and rate limits

- 5 failed logins for one email within 15 minutes locks that email for 15 minutes.
- 20 failed attempts from one IP within 15 minutes blocks that IP for 15 minutes.
- Reset and verification emails: at most 3 per email per hour.
- Limits are counted in `login_attempts` (Postgres), so they work with more than one server process.

### Sessions

- The cookie `seosys_session` is 32 random bytes; only its hash is stored. Flags: `HttpOnly`, `Secure`
  (outside `development`), `SameSite=Lax`, `Path=/`.
- Idle timeout 12 hours, absolute 30 days; admin 8 hours absolute. `last_seen_at` is written at most
  once a minute per session to keep reads cheap.
- A new session ID is issued at login and when two-step passes. Logout deletes the row.
- Password reset or change ends every other session for that user.
- A "Where you're signed in" page lists sessions (browser, IP, last seen) and can end any of them.
- **CSRF**: every non-GET request must send header `X-CSRF-Token` matching the session's token. The
  portal reads it from `/api/auth/me`. The Stripe webhook and the OAuth callback are exempt; both are
  verified by signature or one-time state.

## 6. Permissions

One table in `backend/seo_platform/permissions.py` maps each action to the roles allowed. Every route
declares its action with a FastAPI dependency `require("<action>")`. A test walks every registered
route and fails if one has no declared action (public routes declare `public`).

| Action | Admin | Owner | Member | Member + can approve | Signed in, no package | Public |
|---|---|---|---|---|---|---|
| Free website check, public pages | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Own profile, sessions, two-step | ✓ | ✓ | ✓ | ✓ | ✓ | |
| Buy a package | | | | | ✓ (verified email) | |
| View client dashboard, findings, changes, reports, Google data | ✓ | ✓ | ✓ | ✓ | | |
| Comment on a change | ✓ | ✓ | ✓ | ✓ | | |
| Approve or reject a change | | ✓ | | ✓ | | |
| Client settings (auto-approve, freeze, require two-step) | ✓ | ✓ | | | | |
| Connect or disconnect Google, choose properties | ✓ | ✓ | | | | |
| Invite, remove, change member roles | ✓ | ✓ | | | | |
| Billing (Stripe portal) | | ✓ | | | | |
| Export client data | ✓ | ✓ | | | | |
| Run audits, draft changes, deploy, roll back, sample AI answers, PageSpeed | ✓ | | | | | |
| All clients and users, suspend, activate manually, transfer ownership | ✓ | | | | | |

Account status narrows this further:

- `past_due`: everything still visible; deploys and new audits pause; owner sees a banner.
- `cancelled`: read-only for 30 days from `cancelled_at`, then `closed`.
- `closed`: no portal access; the owner can still export data for 30 more days, then data is deleted by
  the maintenance job (deletion is logged).

The maintenance job (`python -m seo_platform maintenance`) moves accounts through these states, deletes
expired sessions, tokens and old login attempts, and retries failed emails. It is safe to run any number
of times; locally it also runs hourly inside the app, and in production it runs on a scheduler.
- A `suspended` user cannot sign in at all.

## 7. Billing

- Plans come from `backend/seo_platform/plans.py` (name, Stripe price ID from env, what's included).
  Prices follow `notes/Project/Business and Offer.md` and are set in the Stripe dashboard.
- **Buy**: `POST /api/billing/checkout` creates a Stripe Checkout Session (subscription mode) and returns
  its URL. Requires a verified email and no existing client membership as owner.
- **Webhook** `POST /api/billing/webhook`: signature checked with `STRIPE_WEBHOOK_SECRET`; each event id
  stored once in `stripe_events`. Handled events:
  - `checkout.session.completed`: create the client (status `active`), the owner membership, and the
    subscription row; send a welcome email.
  - `customer.subscription.updated` / `deleted`: sync status (`past_due`, `cancelled`).
  - `invoice.payment_failed` / `invoice.paid`: set or clear `past_due`; email the owner.
- **Manage**: `POST /api/billing/portal` returns a Stripe Billing Portal URL (change card, cancel,
  invoices).
- **Admin**: can mark a client active manually (for invoice or bank-transfer clients); logged.
- Local testing uses the Stripe CLI (`stripe listen --forward-to localhost:8000/api/billing/webhook`).
  Automated tests use a fake Stripe (same pattern as `FakeGoogle`) and signed test payloads.

## 8. Email

`backend/seo_platform/mailer.py` sends through SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `MAIL_FROM`) from the `email_outbox` table (section 4). Locally this is Mailpit. Templates: verify email, reset password,
invite, welcome, payment failed, two-step changed, new sign-in from a new device. Each has HTML and
plain text, with copy in one module.

## 9. Pages

**Public**: home, how it works, packages, free website check, about, contact, privacy, terms, sign up,
log in, verify email, forgot and reset password, accept invite.

**Account** (any signed-in user): profile, password, two-step setup, recovery codes, sessions.

**Client portal** (members of a client): the existing dashboard, findings, changes, AI visibility, Google
data and reports; team and invites (owner); billing (owner); settings (owner). Buttons only render when
the user has the action, and the API enforces it regardless.

**Admin**: clients, users, sign-ups, subscriptions, suspend and reactivate, manual activation, audit log.

A client switcher appears when a user belongs to more than one client.

Design: new public visual identity through the frontend-design skill, with a placeholder wordmark until
the logo arrives. All copy through `labels.ts` (sentence case, plain English). "Proof of concept"
wording is removed from code, UI and docs.

## 10. Existing code

- `db.py` is rewritten on SQLAlchemy Core and psycopg. `Database` and `ClientRepo` keep their public
  methods so the rules engine, crawler, change pipeline and Google connector need only small edits.
- Schema moves from the inline `SCHEMA` string to Alembic migrations under `backend/migrations/`.
  Migration 0001 creates the full schema above.
- The `X-Role` / `X-Actor` headers are removed. `actor` strings come from the signed-in user.
- Current demo data becomes `python -m seo_platform seed --demo`, which creates the admin, one user per
  client role, and clients in each status. Admin credentials for local use come from
  `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` in `.env`.
- No data is migrated from SQLite; the local SQLite file holds demo data only.

## 11. Configuration and production readiness

- All settings from environment variables, validated at startup in `config.py`. `APP_ENV` is
  `development`, `test` or `production`.
- In `production` the app refuses to start if any required secret is missing or equal to an example
  value, if `APP_BASE_URL` is not HTTPS, or if debug features are on.
- Security headers on every response: `Content-Security-Policy` (self only, no inline script),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `X-Frame-Options: DENY`, `Permissions-Policy`, and `Strict-Transport-Security` in production.
- `GET /healthz` (process up) and `GET /readyz` (database reachable, migrations current).
- Structured JSON logs with a request ID; secrets and tokens never logged.
- Front-end build files get content hashes in their names, so browsers load new versions without
  Ctrl+F5.
- `ops/`: production checklist, environment variable reference, `backup.ps1` / `restore.ps1`
  (`pg_dump` / `pg_restore`).

## 12. Testing

- Tests run against Postgres (`seosys_test`), reset between tests by truncating tables. `run-tests.ps1`
  starts Docker services if needed.
- **Permission matrix**: generated from the permission table; every route × every role (admin, owner,
  member, approver member, no package, anonymous, suspended, past-due owner, cancelled owner, other
  client's owner), asserting allowed or refused.
- **Unit and API tests** for every flow in sections 5 to 8, including expiry using a replaceable clock
  (`seo_platform.clock`).
- **Testability hooks for Playwright later**: `data-testid` on every interactive element; Mailpit API
  for reading emails; `POST /api/test/reset` exists only when `APP_ENV=test`; seed fixtures per role.
- The 41 existing tests are kept and moved to the new auth (sessions instead of role headers).
- Frontend typecheck stays green.

## 13. Order of work

1. Docker services, Alembic, SQLAlchemy data layer; existing tests pass on Postgres.
2. Users, sessions, sign-up, login, verification, reset, Google sign-in, two-step, Mailpit email.
3. Permission table, route enforcement, row-level security, permission-matrix tests.
4. Stripe checkout, webhooks, account statuses, billing pages.
5. Public site, account pages, portal changes by role, client switcher.
6. Admin pages, security headers, hashed build files, ops folder, production checklist.

## 14. Out of scope here

Production hosting and DNS, a real email provider, e-signature, the GitHub Pages test site, WordPress,
AI engines, DataForSEO, Shopify and the GitHub App. Each is a later sub-project.
