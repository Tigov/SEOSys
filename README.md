# SEO Platform: local proof of concept

A working slice of the platform described in the [functional design](docs/functional-design.md) (FDD) and [technical design](docs/technical-design.md) (TDD), running entirely on your PC. It shows the loop that matters most:

**crawl a client site → find problems with evidence → draft fixes → client approves → deploy through a plugin-style API → re-check the live page → roll back automatically if anything broke → report.**

It includes a fake client, *Lone Star Comfort HVAC*. Its demo WordPress-style website runs locally with real SEO problems built in, so you can watch the whole cycle without touching a real site.

## Run it

You need **Python 3.10 or newer** on Windows (python.org installer or `winget install Python.Python.3.12`). Node is only needed if you change the portal (see below).

1. Double-click **`start.bat`**, or run `powershell -ExecutionPolicy Bypass -File .\start.ps1` in this folder.
2. The first run creates a Python environment and installs packages (about a minute). Your browser then opens **http://localhost:8000**.
3. Press **Ctrl+C** in the window to stop.

| What | Where |
| --- | --- |
| Portal (staff console and client view) | http://localhost:8000 |
| API docs (try every endpoint) | http://localhost:8000/docs |
| Demo client website | http://127.0.0.1:8001 |

The Python environment, database and demo-site state are stored in `%LOCALAPPDATA%\ProjectSEOSys`, not in this OneDrive folder, so OneDrive doesn't sync library files or lock the database. To start over, use **Reset demo** in the portal or run `start.bat -Reset`.

## A 5-minute walkthrough

1. **Overview → Run audit.** The crawler reads the demo site the way Google does. Health is about 29/100.
2. **Overview → Sample AI answers.** This gives a baseline of how often (simulated) ChatGPT, Gemini, Perplexity and Google AI Overviews mention the business.
3. **Findings.** Each issue has a severity, evidence and a recommended fix. Click **Draft fixes for N issues**.
4. **Changes.** Each draft shows *Now* versus *After*. Title and description changes show a real Google-result preview. Click **Send drafts for approval**.
5. Switch **Viewing as → Client owner** (top left). The owner sees what's waiting and approves. Nothing changes on the site until they do.
6. Switch back to **Strategist**. Click **Make the next deploy fail**, then **Deploy approved**. Every change is applied and checked live. The sabotaged one fails its checks and is **rolled back automatically**, with an alert on the Overview.
7. **Run audit** again: health jumps to about 81. **Sample AI answers** again: the mention rate rises because schema, AI-crawler access and descriptions were fixed.
8. **Open monthly report** for the client-facing summary, and **Activity** for the full audit trail and running cost.
9. **Free website check** in the left rail is the public lead-capture grader.

Things to try: turn on **Freeze all deployments** (deploys are refused), or as the client turn on **Auto-approve low-risk changes**. Edit a page on the demo site between approval and deploy and the platform detects the drift and refuses to overwrite it.

## What's real and what's simulated

| Real (works the same as production) | Simulated or simplified for local use |
| --- | --- |
| Crawler, redirect chains, robots.txt and sitemap parsing | AI engines: deterministic simulation behind the real `AIEngine` interface |
| Rules engine with evidence; health score | SQLite instead of Postgres (scoping enforced in `ClientRepo` instead of row-level security) |
| Fix generator, risk levels, policy linter | Roles via a header toggle instead of Cognito login |
| Change state machine, approvals, freeze, drift detection | One deploy adapter (WordPress-style); Shopify and GitHub are later |
| Signed (HMAC + timestamp + nonce) plugin API | Text written by templates unless `ANTHROPIC_API_KEY` is set in `.env` |
| Post-deploy verification and automatic rollback | Usage costs are estimates |
| Tenant isolation, audit log, data export, cost metering, budget cap | |

With an Anthropic API key in `.env` (copy `.env.example`), titles, descriptions, alt text and the report summary are written by Claude instead of templates. They still go through the policy linter and client approval.

## Project layout

```
start.bat / start.ps1        run everything on Windows (start.sh for macOS/Linux)
run-tests.ps1                run the test suite
backend/
  seo_platform/              the platform (FastAPI)
    api.py                   HTTP routes + serves the portal
    db.py                    SQLite schema, ClientRepo (every query scoped to one client)
    crawler.py               reads public pages like a search engine
    rules.py                 findings with evidence, health score
    fixes.py                 finding -> change requests (before/after, risk, policy flags)
    changes.py               approvals, deploy, verification, rollback
    visibility.py            AI-visibility sampling (simulated engines)
    services.py              audit, grader, summary, monthly report
    policy.py                blocks guarantee / #1 / paid-link language
    adapters/                llm.py (Claude or offline), site_wp.py (signed plugin client)
    static/                  built portal (already included)
  demo_site/                 the fake client website + its "plugin" API
  tests/                     18 end-to-end tests (pipeline, roles, freeze, rollback, isolation, security...)
frontend/                    React + TypeScript portal source
docs/                        functional design, technical design, research, FDD coverage
```

## Documents

- [Functional design (FDD)](docs/functional-design.md): what the platform must do, packages, modules and requirements
- [Technical design (TDD)](docs/technical-design.md): architecture, data model, integrations, security, costs and build plan
- [Market research](docs/research-seo-business-landscape.md): the SEO services landscape the design is based on
- [FDD coverage](docs/fdd-coverage.md): which requirements this proof of concept implements
- [Contributing](CONTRIBUTING.md): rules for working on the code

## Tests

`.\run-tests.ps1` (after `start.ps1` has run once). The 18 tests drive the whole pipeline against an in-memory copy of the demo site. They cover:
- seeded issues detected, with evidence
- score improves after fixes
- automatic rollback on a broken deploy
- manual rollback
- role rules
- freeze switch
- auto-approval opt-in
- drift detection
- tenant isolation
- AI visibility responds to fixes
- grader and report
- plugin API rejects unsigned, replayed and bad-timestamp requests
- signing key never returned by the API
- parallel deploys write only once
- schema markup can't break out of its script tag
- policy linter
- robots.txt rewrite

## Changing the portal

The built portal is already in `backend/seo_platform/static`, so you only need Node (20+) to change it:

```
cd frontend
npm install
npm run watch        # rebuilds on save; refresh http://localhost:8000
npm run typecheck
```

Tip: OneDrive will try to sync `frontend/node_modules`. Right-click the folder and choose **Free up space**, or exclude it.

## Code-review graph

The repo is set up for [code-review-graph](https://github.com/tirth8205/code-review-graph). **CONTRIBUTING.md requires checking the graph every time you look through the code**: search, callers, impact radius and review all go through the graph first, and the graph is updated after every edit.

```
build-graph.bat               # double-click: build the graph, show stats, open the interactive map
build-graph.bat -Install      # also register the graph's MCP server with your editor
code-review-graph update      # after edits (or: code-review-graph watch)
```

The graph lives in `.code-review-graph/` (git-ignored). `.code-review-graphignore` keeps `node_modules`, the built portal and local data out of it.

## From proof of concept to production

Following TDD section 14:
1. Swap SQLite for Postgres with row-level security, and the role header for Cognito.
2. Replace the simulated engines with real adapters (OpenAI, Gemini, Perplexity, DataForSEO for AI Overviews).
3. Turn `demo_site`'s plugin API into a real WordPress plugin, then add the Shopify app and GitHub App adapters behind the same `apply / current_value` interface.
4. Move long jobs (crawls, sampling) onto SQS workers.
