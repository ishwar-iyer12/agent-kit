# agent-kit

Shared pieces of the agent-first engineering workflow. One copy, every project uses it.

| Part | Where | Used by |
|---|---|---|
| Claude Code plugin (skills) | `plugins/agent-kit/skills/*` | Engineers' CLI, Orca workers, cloud tasks, CI reviewer |
| Reusable GitHub workflows | `.github/workflows/{review,claude,deploy-staging}.yml` | Every project via thin callers |
| Overnight runner + tracker adapters | `runner/` | Each engineer's Windows machine (Orca automation or Task Scheduler) |
| Config schemas | `schema/*.example` | `agent.json` per project, `projects.json` per machine, `.claude/settings.json` per project |
| Cloud scheduled-task prompts | `prompts/` | claude.ai/code/routines |
| Process docs | `docs/` | Humans |

## Skills

`/agent-kit:implement-card <url|key>` · `/agent-kit:e2e` · `/agent-kit:release-notes` · `/agent-kit:review-checklist` · `/agent-kit:design-tokens` · `/agent-kit:setup-repo`

Install in a project by adding to `.claude/settings.json` (see `schema/settings.json.example`):

```json
{ "extraKnownMarketplaces": { "agent-kit": { "source": { "source": "github", "repo": "ishwar-iyer12/agent-kit" } } },
  "enabledPlugins": { "agent-kit@agent-kit": true } }
```

For a one-off: `claude plugin marketplace add ishwar-iyer12/agent-kit && claude plugin install agent-kit@agent-kit`.

## Thin callers

Copy from `examples/` into `<project>/.github/workflows/`. Callers must grant the `permissions` shown in the examples (a called workflow cannot exceed its caller; `id-token: write` is not in the default token). `ci.yml` is project-specific; the other three are one `uses:` line each with `secrets: inherit`.

Secrets the reusable workflows read (set once at org level, or per repo): `ANTHROPIC_API_KEY` (preferred) or `CLAUDE_CODE_OAUTH_TOKEN` (interim), `SLACK_WEBHOOK_URL`, `TRELLO_KEY`+`TRELLO_TOKEN` or `LINEAR_API_KEY`, `STAGING_USER`, `STAGING_SSH_KEY`. Variables: `STAGING_ENABLED`, `STAGING_HOST`. The Claude GitHub App must be installed on each repo.

Pin callers to a tag (`@v0.2.0`) once the kit stabilises; `@main` while iterating.

## Runner

```
copy schema\projects.json.example runner\projects.json   # edit paths, enabled flags
pwsh runner\overnight.ps1 -DryRun                         # lists what it would pick
pwsh runner\overnight.ps1 -Project agent-workflow-demo -MaxCards 1
pwsh runner\install-task.ps1                              # Task Scheduler fallback, 23:00 Sun-Thu
```

Each project supplies `agent.json` (tracker, base branch, test commands) and a local `.env` with the tracker token and Slack webhook. Labels: `cloud` = skipped locally, picked by the cloud nightly; `serial` = run one at a time after the parallel batch.

Orca automation (per engineer): `orca automations create --name "Overnight implement" --disabled --trigger "0 23 * * 0-4" --timezone Asia/Kolkata --provider claude --repo name:agent-kit --prompt "Run pwsh runner/overnight.ps1 and print the newest overnight-report" --json`, test with `orca automations run <id>`, then enable.

## Tracker contract

Both adapters normalise items to `{ tracker, id, url, title, labels[], position }` and expose `Get-TrackerReadyItems` / `Move-TrackerItem`. States are named in `agent.json`: `ready → inProgress → inReview → done` (+ `needsSpec`). Trello = lists on one board; Linear = workflow states on one team plus the `agent-ready` label.

## Staging

One small EC2 for all projects, compose per project, provisioned by `infra/staging/provision-staging.ps1` (Ubuntu 24.04, docker, `deploy` user with your SSH key, repos cloned under `/home/deploy`). Needs `aws login` first. The script prints the `gh variable set` / `gh secret set` lines for each project repo. `STAGING_SCHEME=http` until a DNS name + TLS exist.

## Known limits

- Paper MCP is local-only. `implement-card` commits a design export (`design/<id>/`) so the CI reviewer can check drift; cards needing Paper must not be labelled `cloud`.
- `claude-code-action` receives both credential inputs; an empty one is ignored. If it ever refuses an empty `anthropic_api_key`, delete that line in `review.yml`/`claude.yml` until the key exists.
- Orca orchestration is experimental; field names (`taskId`, `dispatchId`) are read with fallbacks. `orca skills get orchestration --full` has the current schema.
