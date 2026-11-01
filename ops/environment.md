# Environment variables

All settings come from the environment (locally, `.env`, which `start.bat` loads). `backend/seo_platform/config.py`
is the source of truth.

| Variable | Local default | Production |
| --- | --- | --- |
| `APP_ENV` | `development` | `production` |
| `APP_BASE_URL` | `http://localhost:8000` | Your https address. Used in email links and Stripe redirects. |
| `DATABASE_URL` | local `seosys_app` role | App role connection string. The role must own no tables. |
| `DATABASE_OWNER_URL` | local `seosys_owner` role | Owner role, for migrations only. Don't give it to the running app. |
| `DB_POOL_SIZE` | `5` | Size for your instance |
| `APP_ENCRYPTION_KEY` | development key | 32 random bytes, base64. Required. |
| `APP_ENCRYPTION_KEY_VERSION` | `1` | Bump when rotating |
| `APP_ENCRYPTION_KEYS_OLD` | empty | `v1=<old key>` during a rotation |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS` | Mailpit on 1025, no TLS | Your email provider, TLS on |
| `MAIL_FROM` | `SEOSys <no-reply@seosys.local>` | An address on your domain |
| `STRIPE_SECRET_KEY` | empty (buying disabled) | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | empty | From the Stripe webhook endpoint |
| `STRIPE_PRICE_AUDIT`, `STRIPE_PRICE_LOCAL`, `STRIPE_PRICE_GROWTH` | empty (package shows "Talk to us") | Live price IDs |
| `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD` | empty | Only for the first `seed`, then remove the password |
| `SEED_DEMO_PASSWORD` | built-in | Never used in production |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | empty | Your published OAuth client |
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:8000/api/oauth/google/callback` | `https://<domain>/api/oauth/google/callback` |
| `GOOGLE_PAGESPEED_API_KEY` | empty | API key restricted to the PageSpeed Insights API |
| `ANTHROPIC_API_KEY`, `SEO_LLM_MODEL` | empty (template writer) | Optional |
| `ALLOW_PRIVATE_HOSTS` | `true` (the demo site is local) | `false` |
| `CRAWL_MAX_PAGES` | `50` | As needed |
| `CLIENT_MONTHLY_BUDGET_USD` | `80` | Running-cost cap per client |
| `DEMO_SITE_URL`, `DEMO_SITE_SECRET`, `DEMO_SITE_STATE` | local demo site | Not used |
