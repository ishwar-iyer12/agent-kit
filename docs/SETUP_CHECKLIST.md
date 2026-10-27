# One-time setup checklist

Everything that lives outside the repo. Tick in order. Owner column = who has the credentials.

## A. GitHub (owner: Ishwar)

- [ ] Repo exists, default branch `temp-prod`, `main` protected (PR + CI required, no direct push).
- [ ] Install the Claude GitHub App on the repo: https://github.com/apps/claude (needed by `claude-code-action` to post comments / push fixes).
- [x] Claude GitHub App installed (2026-10-23).
- [ ] **BLOCKED 2026-10-23** — Ishwar has no own Anthropic login; the Max seat is Mohit's account. Unblock either way:
  - (a) interim: Mohit approves `claude setup-token` URL and sends back the code → `gh secret set CLAUDE_CODE_OAUTH_TOKEN -R ishwar-iyer12/agent-workflow-demo`. Workflows currently expect this secret.
  - (b) proper: Console org owner invites Ishwar's own email as Developer → Console → workspace `ci-review` → API key → spend limit **$150**, alert **$100** → `gh secret set ANTHROPIC_API_KEY ...` → flip `claude_code_oauth_token:` back to `anthropic_api_key:` in both Claude workflows.
  - Also request an own claude.ai seat for Ishwar: connectors and scheduled tasks (sections C–D) are per-account and should not live under Mohit's login.
- [ ] Labels: `deep-review`, `deploy-staging`, `client:clevergear`, `client:greystone`.
- [ ] First PR opened → `Claude Code Review` posts inline comments within ~5 min. If not: Actions tab → run log.

## B. Trello (owner: Devang)

- [ ] Board lists exactly: `Inbox`, `Needs Spec`, `Agent Ready`, `In Progress`, `In Review`, `Done`.
- [ ] Labels: `cloud`, `client:clevergear`, `client:greystone`, `P0`, `P1`, `P2`, `Draft Metric`.
- [ ] Card template "Feature" with description headings *Source*, *Layer*, *Notes* and checklist *Acceptance criteria*.
- [ ] Power-Up: GitHub (so PR links show on cards) — optional.
- [ ] Each engineer: Trello API key + token (https://trello.com/power-ups/admin → new Power-Up → API key → token) into local `.env` as `TRELLO_KEY` / `TRELLO_TOKEN`, plus `TRELLO_BOARD_ID` (board URL → `.json` → `id`).
- [ ] Same key/token as repo secrets `TRELLO_KEY` / `TRELLO_TOKEN` for the deploy workflow's card comments.

## C. claude.ai connectors (owner: each engineer, own account)

https://claude.ai/customize/connectors

- [ ] **Slack** — already installed in the workspace; connect your account.
- [ ] **Trello** — add connector, authorize against the team board.
- [ ] **Granola** — add custom connector, URL `https://mcp.granola.ai/mcp`, OAuth sign-in.
- [ ] **GitHub** — connected at https://claude.ai/code, repo authorized (needed for cloud sessions and scheduled tasks).

## D. Cloud scheduled tasks (owner: Ishwar's account; tasks are per-account)

https://claude.ai/code/routines → New task → Set up manually. Prompts in `docs/prompts/`.

- [ ] **Intake triage** — trigger: Schedule, hourly 09:07–21:07 IST weekdays (`7 3-15 * * 1-5` UTC). No repository. Connectors: Slack, Granola, Trello only. Model: Sonnet 5.5. Prompt: `docs/prompts/intake-triage.md`. Also add an **API** trigger; store the fire URL + token in the team password manager so anyone can force a run with curl.
- [ ] **Nightly implement (cloud)** — trigger: Schedule 23:37 IST weekdays. Repository: this repo. Environment: Default (trusted), setup script `cd web && corepack enable && pnpm install --frozen-lockfile && cd ../api && pip install -r requirements.txt`. Connectors: Trello, Slack. Model: Opus 5.5. Prompt: `docs/prompts/nightly-cloud.md`.
- [ ] `Run now` once on each; open the run, read the transcript, confirm it did what the prompt says. Green status ≠ success.

## E. Slack (owner: workspace admin)

- [ ] Channel `#eng-agent` (overnight reports, deploy links, intake digests). Invite `@Claude` (`/invite @Claude`) to `#eng` and `#eng-agent`.
- [ ] Incoming webhook for `#eng-agent` → repo secret `SLACK_WEBHOOK_URL` and local `.env`.
- [ ] Claude app → App Home → Routing mode **Code + Chat**; each engineer connects their Claude account.

## F. Orca (owner: each engineer, Windows)

- [x] `orca status --json` reachable (2026-10-23). Settings → Experimental → enable orchestration still to confirm in UI.
- [x] Repo registered in Orca, base ref `temp-prod` (2026-10-23). Worktree setup script still to set: `cd web && pnpm install --frozen-lockfile; cd ../api && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt`.
- [ ] Default agent Claude Code, model Opus 5.5.
- [x] Automation `Overnight implement (local)` created **disabled** (2026-10-23). Enable after a successful `orca automations run <id>`. Original command for reference: `orca automations create --disabled --trigger "0 23 * * 0-4" --timezone Asia/Kolkata --provider claude --repo agent-workflow-demo --prompt "Run pwsh runner/overnight.ps1 and report the contents of the newest overnight-report-*.md" --json` → test with `orca automations run <id> --json` → enable.
- [ ] Fallback without Orca: Windows Task Scheduler → `pwsh -File runner\overnight.ps1 -Mode claude` at 23:00.
- [ ] Power plan: never sleep when plugged in. Mobile companion app installed for escalation pings.

## G. Staging (owner: Ishwar / Parichay; after demo proves out)

- [ ] Small EC2 (t3.small is fine), docker + compose, repo cloned to `~/agent-workflow-demo`, `.env` filled.
- [ ] Repo variables: `STAGING_ENABLED=true`, `STAGING_HOST=<dns>`. Secrets: `STAGING_USER`, `STAGING_SSH_KEY`.
- [ ] Push to `temp-prod` → `Deploy staging` run green → Slack message with link.
