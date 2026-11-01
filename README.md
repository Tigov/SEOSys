# SEOSys

SEOSys is a software-led SEO service for local businesses. It is a public website with a free website check and
online sign-up, a client portal, and an agency console, all in one app. The work loop at its heart:

**crawl a client site → find problems with evidence → draft fixes → client approves → deploy through the site's plugin → re-check the live page → roll back automatically if anything broke → report.**

It runs fully on your PC: Postgres and an email catcher in Docker, the app on Windows. Moving to a hosted environment
is configuration only (see [ops/production-checklist.md](ops/production-checklist.md)).

## Run it

You need **Python 3.12+**, **Docker Desktop** (running), and on first run an internet connection for packages.
Node is only needed if you change the portal.

1. Copy `.env.example` to `.env`. Set `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD` (12+ characters) for your admin
   login, and optionally `SEED_DEMO_PASSWORD` for the demo people.
2. Double-click **`start.bat`**. It starts Postgres and Mailpit in Docker, migrates the database, creates the admin
   and demo data, and opens **http://localhost:8000**.
3. Log in as the admin. You'll be asked to set up two-step login with an authenticator app the first time.
4. Press **Ctrl+C** to stop the app. `docker compose stop` stops the database and mail catcher.

| What | Where |
| --- | --- |
| Website, portal and agency console | http://localhost:8000 |
| Emails the app sends (Mailpit) | http://localhost:8025 |
| API docs (development only) | http://localhost:8000/docs |
| Demo client website | http://127.0.0.1:8001 |
| Health checks | http://localhost:8000/healthz, http://localhost:8000/readyz |

Demo people (password `SEED_DEMO_PASSWORD`): `owner@demo.seosys.local`, `member@demo.seosys.local` (can view),
`approver@demo.seosys.local` (can approve changes). They belong to the demo client, *Lone Star Comfort HVAC*.

The Python environment and demo-site state live in `%LOCALAPPDATA%\ProjectSEOSys`, not in OneDrive. To start over,
run `start.bat -Reset`.

## Who can do what

- **Admin** (the agency): every client, audits, drafting and deploying changes, the People page and security log.
  Two-step login is required. The admin can't approve changes for a client.
- **Client owner**: their dashboard, approving changes, settings, team, billing and data export.
- **Client member**: sees everything for their business. Can approve changes only if the owner ticks "Can approve".
- **Signed in, no package**: the public site plus their account, and can buy a package.

The full table is in [permissions.py](backend/seo_platform/permissions.py) and is enforced on every route. Postgres
row-level security keeps each client's rows apart as a second lock.

## Security, briefly

Passwords use argon2id with a breached-password blocklist; sessions live in Postgres behind an HttpOnly cookie; every
change sends a CSRF token; lockouts and rate limits per email and IP; optional two-step login (required for the
admin); Google tokens, website keys and two-step secrets are encrypted at rest; strict security headers; nothing in
answers, emails or timing reveals whether an email has an account. Details: the
[design spec](docs/superpowers/specs/2026-10-31-production-foundation-design.md).

## What's real and what's still simulated

| Real | Simulated or not built yet |
| --- | --- |
| Accounts, two-step login, Google sign-in, teams and invitations | AI engines: deterministic simulation behind the real `AIEngine` interface |
| Stripe checkout and billing portal (test mode locally) | Rankings and keyword data (DataForSEO is a later step) |
| Crawler, rules engine with evidence, health score | Only the WordPress-style deploy adapter; Shopify and GitHub come later |
| Change approvals, deploys through a signed plugin API, live verification, automatic rollback | The WordPress plugin itself (the demo site plays its part) |
| Google Search Console, Analytics and PageSpeed Insights | Text is written by templates unless `ANTHROPIC_API_KEY` is set |
| Postgres with migrations and row-level security, email outbox, maintenance job | |

## Project layout

```
start.bat / start.ps1        run everything on Windows
run-tests.ps1                run the test suite (needs Docker running)
docker-compose.yml           Postgres 17 and Mailpit
ops/                         production checklist, environment variables, backup and restore
backend/
  alembic.ini, migrations/   database migrations (schema.py is the reference)
  seo_platform/
    api.py                   HTTP routes; serves the portal
    permissions.py           who may do what
    auth/                    passwords, sessions, two-step login, Google sign-in
    billing.py, plans.py     Stripe checkout, webhooks, packages
    team.py                  invitations, approval rights, ownership
    db.py, schema.py         Postgres access (ClientRepo scopes every query to one client)
    mailer.py, email_copy.py email outbox and templates
    maintenance.py           closes cancelled accounts, deletes expired data
    middleware.py            security headers, request ids, JSON logs
    crawler.py, rules.py, fixes.py, changes.py, visibility.py, services.py, policy.py
    adapters/                Google, Claude or offline writer, signed WordPress plugin client
  demo_site/                 the fake client website and its plugin API
  tests/                     backend tests, including a permission matrix over every route
frontend/                    React + TypeScript source (public site, accounts, portal, admin)
docs/                        functional and technical design, research, specs and plans
```

## Tests

`.\run-tests.ps1` runs the backend tests against the `seosys_test` database in Docker. They cover the SEO pipeline,
every account flow, two-step login, Google, billing webhooks (including duplicate deliveries), teams, row-level
security, security headers, and a matrix that calls every route as eleven kinds of person.

`cd frontend; npm run typecheck` checks the portal.

## Changing the portal

The built portal is in `backend/seo_platform/static`. With Node 20+:

```
cd frontend
npm install
npm run watch        # rebuilds on save; refresh http://localhost:8000
npm run typecheck
```

Built files carry a hash in their names, so browsers load a new version on the next refresh.

## Documents

- [Functional design (FDD)](docs/functional-design.md) and [technical design (TDD)](docs/technical-design.md)
- [Production foundation spec](docs/superpowers/specs/2026-10-31-production-foundation-design.md) and
  [plan](docs/superpowers/plans/2026-10-31-production-foundation.md)
- [Market research](docs/research-seo-business-landscape.md) and [FDD coverage](docs/fdd-coverage.md)
- [Contributing](CONTRIBUTING.md)

## Code-review graph

The repo is set up for [code-review-graph](https://github.com/tirth8205/code-review-graph). CONTRIBUTING.md requires
checking the graph first when looking through the code, and updating it after edits.

```
build-graph.bat               # build the graph and open the interactive map
code-review-graph update      # after edits
```
