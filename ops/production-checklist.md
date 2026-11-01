# Production checklist

Moving SEOSys from this PC to a hosted environment is configuration, not code. Work down this list.
The app refuses to start with `APP_ENV=production` while any of the checks it can see are failing.

## Before the first real customer

- [ ] **Legal**: have a lawyer review the privacy policy and terms (the site's pages are working drafts).
- [ ] **Google sign-in app**: publish the OAuth app in Google Cloud and pass Google's verification (needs a privacy
      policy URL, a homepage on your own domain, and the scopes explained). Until then refresh tokens expire after 7 days.
- [ ] **Stripe**: create the live products and prices; set `STRIPE_PRICE_AUDIT`, `STRIPE_PRICE_LOCAL`,
      `STRIPE_PRICE_GROWTH`; add a webhook endpoint for `https://<your domain>/api/billing/webhook` with the events
      `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`,
      `invoice.payment_failed`; set `STRIPE_WEBHOOK_SECRET` from it. Turn on the Stripe billing portal.
- [ ] **Email**: a real provider (Amazon SES, Postmark or similar) with SPF, DKIM and DMARC on your domain.

## Infrastructure

- [ ] **Database**: managed Postgres 17 (e.g. AWS RDS) with automated backups and encryption at rest. Create two
      roles exactly as `ops/postgres/init.sql` does: an owner for migrations and `seosys_app` for the app, with a
      strong password each.
- [ ] **App**: run `uvicorn seo_platform.api:app --proxy-headers --forwarded-allow-ips=<load balancer>` behind HTTPS.
      Health check `/healthz`, readiness `/readyz`.
- [ ] **Deploy step**: `python -m alembic upgrade head` (as the owner role) before the new version takes traffic.
- [ ] **Scheduler**: run `python -m seo_platform maintenance` hourly.
- [ ] **Secrets**: keep them in a secrets manager, not in files. Generate a fresh `APP_ENCRYPTION_KEY`
      and keep it safe: without it, stored Google tokens and website keys can't be read.
- [ ] **Logs**: ship the JSON logs to your log service; alert on `level=error`.

## Environment

See [environment.md](environment.md) for every variable. Required in production:
`APP_ENV=production`, `APP_BASE_URL` (https), `DATABASE_URL`, `DATABASE_OWNER_URL` (migrations only),
`APP_ENCRYPTION_KEY`, `SMTP_*` with `SMTP_TLS=true`, `MAIL_FROM`, `STRIPE_SECRET_KEY` (live), `STRIPE_WEBHOOK_SECRET`,
`ALLOW_PRIVATE_HOSTS=false`, `GOOGLE_OAUTH_*` with the production redirect URI, `GOOGLE_PAGESPEED_API_KEY`.

## First admin

Set `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD`, run `python -m seo_platform seed` once, log in and set up two-step
login, then remove `SEED_ADMIN_PASSWORD` from the environment.

## Backups

`ops/backup.ps1` and `ops/restore.ps1` wrap `pg_dump` / `pg_restore`. Test a restore before launch, and on a schedule
after it.
