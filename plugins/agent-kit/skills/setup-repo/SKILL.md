---
name: setup-repo
description: Wire a project repo into the agent-first workflow — agent.json, .claude/settings.json marketplace entry, thin workflow callers, CLAUDE.md sections, PR template, labels. Use when onboarding a new or existing repo.
---

# setup-repo

Idempotent. Re-running updates files to the current kit version without clobbering project-specific content.

## 1. Discover

- Detect stacks: `web/package.json` (pnpm/npm), `api/requirements.txt` or `pyproject.toml`, `docker-compose.yml`, `dbt_project.yml`, `cube.js`/`cube.yml`. Record the test commands you find (`pnpm test`, `pytest`, `dbt test`).
- Detect the integration branch: ask if ambiguous. Default `main`; for TrustLayer it is `temp-prod`.
- Ask which tracker (`trello` or `linear`) and get the board id / team key. One project, one tracker.

## 2. Write files

1. `agent.json` from `schema/agent.json.example` in the kit, filled with the discovered values. Keep unknown fields null rather than guessing.
2. `.claude/settings.json`: merge in `extraKnownMarketplaces.agent-kit` and `enabledPlugins["agent-kit@agent-kit"] = true` (schema/settings.json.example). Preserve existing keys.
3. `.github/workflows/`: thin callers of the kit's reusable workflows (see the kit's `README.md` "Thin callers"). `ci.yml` is project-specific: copy the kit's `examples/ci.yml` and adjust job commands to what you discovered. `review.yml`, `claude.yml`, `deploy-staging.yml` are one-liners with `uses: ishwar-iyer12/agent-kit/.github/workflows/<name>.yml@main` and `secrets: inherit`.
4. `.github/pull_request_template.md` with a "How tested", "Design" and `Card:`/`Issue:` line.
5. `CLAUDE.md`: add or update these sections, leaving everything else untouched: **Commands** (from discovery), **Branch rules** (base branch, prefix, one card = one PR, never touch release branch), **Definition of done**, **Review checklist** (pointer to `/agent-kit:review-checklist`), **Environment variables** (pointer to `.env.example`).
6. `.env.example`: ensure tracker + runner variables exist (`TRELLO_KEY`, `TRELLO_TOKEN`, `TRELLO_BOARD_ID` or `LINEAR_API_KEY`; `SLACK_WEBHOOK_URL`).
7. `.gitignore`: `overnight-report*.md`, `.worktrees/`, `.orca/`, `.playwright-mcp/`, `design/**/actual.png` is **not** ignored (reviewer needs it).

## 3. GitHub side (needs `gh` with repo admin)

- Labels: `deep-review`, `deploy-staging`, `cloud`, `serial`, `client:<name>` for each client.
- Default branch = base branch; squash merge only; delete branch on merge.
- Branch protection on base and release branches: PR required, CI required. (Prints the commands; does not run them without confirmation.)
- Secrets expected by the reusable workflows: `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN` interim), `SLACK_WEBHOOK_URL`, `TRELLO_KEY`/`TRELLO_TOKEN` or `LINEAR_API_KEY`, `STAGING_USER`, `STAGING_SSH_KEY`; variables `STAGING_ENABLED`, `STAGING_HOST`. List what is missing; never set them yourself.

## 4. Verify

- `claude --version` in the repo shows the plugin skills (`/agent-kit:implement-card` resolves).
- Open a tiny PR → `CI` and `Claude Code Review` runs appear.
- Print the remaining manual steps from the kit's `docs/SETUP_CHECKLIST.md`.
