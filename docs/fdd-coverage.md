# What SEOSys covers from the FDD

| FDD module | Requirement IDs exercised | Where |
| --- | --- | --- |
| M1 Grader and lead capture | FR-1.1, FR-1.2 (no AI part), FR-1.3 (lead stored; no email sent) | `services.grade`, portal "Free website check" |
| M4 Onboarding and access | FR-4.4 (no password fields), FR-4.5 (audit log) | `adapters/site_wp.py` signed requests, `audit_events` |
| M5 Audit engine | FR-5.1, FR-5.4 (evidence on every finding), FR-5.6 (re-audit resolves findings) | `crawler.py`, `rules.py`, `services.run_audit` |
| M9 AI visibility | FR-9.1, FR-9.3, FR-9.4, FR-9.5 with simulated engines | `visibility.py` |
| M10 Change management | FR-10.1, 10.2, 10.3, 10.5, 10.6, 10.7, 10.9 (WordPress-style adapter only) | `fixes.py`, `changes.py` |
| M11 Reporting | FR-11.1, FR-11.2, FR-11.4 | `services.summary`, `services.report_html`, `/export` |
| M14 Operations | FR-14.4 (metering and budget cap), FR-14.5 (audit log) | `usage_events`, Activity tab |
| Business rules | BR-1, BR-3 (policy linter), BR-4/BR-6 (client approval, no overlays), BR-9 (tenant isolation) | `policy.py`, `changes.py`, `db.ClientRepo` |

Not built yet (next steps): M2 CRM and M3 contracts/billing, OAuth to Google Search Console/GA4/GBP (M4, M7), content workflow (M8), review management (M12), link reclamation (M13), Shopify and GitHub adapters, real AI engines, real auth.
