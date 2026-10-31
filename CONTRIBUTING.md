# Contributing

This repo is a proof of concept of the SEO platform described in [docs/functional-design.md](docs/functional-design.md) and [docs/technical-design.md](docs/technical-design.md). Read README.md first.

## Rule 0: check the code-review graph every time you look through the code

This repo has a code-review-graph knowledge graph (stored in `.code-review-graph/`, built by `build-graph.ps1`).
**Before you read, search or review code, query the graph first.** Open files only for what the graph points you to,
and fall back to plain search/read only when the graph doesn't cover the question.

| Task | Use the graph first (MCP tool, or CLI when MCP isn't connected) |
| --- | --- |
| Find a function, class, route or test | `semantic_search_nodes_tool` / `code-review-graph search "<name>"` |
| Who calls this / what does it call / what imports it | `query_graph_tool` / `code-review-graph query callers_of <name>` (also `callees_of`, `imports_of`, `importers_of`, `tests_for`, `file_summary`) |
| Before changing code: what could break | `get_impact_radius_tool` / `code-review-graph impact --files <paths>` |
| Which flows a change touches | `get_affected_flows_tool` / `code-review-graph flows` |
| Reviewing a change or PR | `detect_changes_tool` + `get_review_context_tool` / `code-review-graph detect-changes --brief` |
| Big-picture structure | `get_architecture_overview_tool`, `list_communities_tool` / `code-review-graph architecture` |
| Is this covered by tests | `query_graph_tool` with `tests_for` / `code-review-graph query tests_for <name>` |

Keep the graph current:
- After you edit files, run `code-review-graph update` (or rely on `code-review-graph watch` / the installed hooks).
- If `code-review-graph status` shows no graph or a stale one, run `.\build-graph.ps1` (or `code-review-graph build`) before continuing.
- In your pull request description, say which graph queries you ran (for example the impact radius) so a reviewer can see it was checked.

## Commands
- Run: `start.ps1` (Windows) or `start.sh`. Platform on :8000, demo client site on :8001.
- Graph: `.\build-graph.ps1` (full build), `code-review-graph update` (after edits), `code-review-graph status`.
- Test: `cd backend; python -m pytest` — must stay green. Add a test for every behaviour you add.
- Portal: `cd frontend; npm run build` (outputs to backend/seo_platform/static), `npm run typecheck` must pass.

## Rules that must never be broken
1. Every client-owned read/write goes through `ClientRepo` (db.py). Never query a client table by id without client_id.
2. Only `changes.deploy_change` and `changes.rollback_change` may write to a client site, and only for an `approved` (or `live`, for rollback) change. Keep role checks (`ROLE_ACTIONS`) and the freeze switch.
3. Every deploy is followed by `verify`; failed checks must trigger automatic rollback and an alert.
4. Findings come only from crawl data (rules.py). LLM output never creates findings; it only drafts text that goes through `policy.lint` and human approval.
5. No password fields anywhere. Site access is via signed adapter requests or OAuth.
6. Never add tactics the business doesn't sell (paid links, mass page generation, doorway pages, fake reviews).
7. Label simulated data as simulated in API responses and UI.
8. Don't add dependencies without approval; keep Python 3.10+ and Windows compatibility.

## Where things go
- New data source or vendor → `seo_platform/adapters/` behind a small interface, metered with `repo.meter`.
- New rule → `rules.py` with evidence + a test in `tests/`.
- New change type → `fixes.py` (proposal + RISK), `changes.verify` (check), the adapter, and the portal's `Changes.tsx` labels.
