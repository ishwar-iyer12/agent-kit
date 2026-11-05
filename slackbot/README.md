# TicketBot

`@TicketBot make a ticket for this` in any Slack thread (or react with :ticket:) and the bot reads the whole thread (or, when mentioned top-level in a channel, the recent channel messages, walking further back on demand), searches the project's tracker, then creates or edits a Trello card / Linear issue with a Source link and testable acceptance criteria. Same card format as the hourly intake routine, so `implement-card` and the overnight runner pick it up unchanged.

Why self-hosted: the official Claude Slack app only uses connectors in channels on Team/Enterprise (Claude Tag); on Max it cannot reach Trello/Linear. This runs on the Claude API ($200 credits) instead, ~$0.03–0.08 per mention on Opus 5.5.

## What it does per request

1. Pulls the full thread (`conversations.replies`), names, permalink, links (Granola, Paper, GitHub).
2. Resolves the project from the channel (`projects.json` → `agent.json` → Trello board or Linear team).
3. Runs Claude (`claude-opus-5-5`, override `TICKETBOT_MODEL`) with six tools: `search_items`, `get_item`, `create_item`, `update_item`, `move_item`, `comment_item`. Strict schemas, prompt cached, server-side fallback on refusals.
4. Guard rails in code, not just prompt: never edits items in In Progress / In Review / Done (comments instead), max 3 creates per request, only `Agent Ready` / `Needs Spec` as targets, no delete tool, scoped to the configured board/team.
5. Replies in the thread with the link(s), the criteria it wrote and at most one clarifying question. Reacts 👀 → ✅/❌. Optional one-line audit to `#eng-agent` via `SLACK_WEBHOOK_URL`.

Instructions it understands: create (default), `add AC: …`, `label it client:acme`, `move to Agent Ready`, `split this into two`, `rename to …`, `add this detail to the existing card`.

## Setup

1. **Slack app**: https://api.slack.com/apps → Create New App → From a manifest → paste `slack-manifest.yaml`. Install to workspace (needs an admin). Copy the Bot User OAuth Token (`xoxb-`, → `SLACK_BOT_TOKEN`). Basic Information → App-Level Tokens → generate with `connections:write` (`xapp-`, → `SLACK_APP_TOKEN`). `/invite @TicketBot` in each channel it should read.
2. **Config**: `cp .env.example .env`, fill it. Write `projects.json` (shape in `../schema/projects.json.example`): one entry per project with `path` to a clone that has `agent.json`, plus `channels`. Trello needs `trello.boardId` in that `agent.json`.
3. **Check**: `python -m ticketbot --check-config` (validates env, lists/states on the board/team, Slack auth; works without the Anthropic key).
4. **Run**:
   - Local: `python -m venv .venv && .venv/Scripts/pip install -r requirements.txt && python -m ticketbot`
   - Staging box: `docker compose up -d --build` in this folder. Repos are cloned under `/home/deploy` by cloud-init and mounted at `/repos`, so `projects.json` paths there look like `/repos/agent-workflow-demo`.
5. **Dry run without Slack**: `python -m ticketbot --dry-run tests/fixtures/thread.json "make a ticket, label it client:clevergear"` runs the real model against an in-memory tracker and prints the cards it would create. Add `--tracker real --project <name>` to hit the actual board.

## Tests

```
.venv/Scripts/python -m pytest -q      # 32 tests: config resolution, Slack markup cleanup, Trello/Linear request shapes (mocked), guard rails, agent loop with a fake Claude
```

## Files

| File | Role |
|---|---|
| `ticketbot/app.py` | Bolt handlers (`app_mention`, `reaction_added`), dedupe, reactions, reply |
| `ticketbot/context.py` | thread → text, mention/link cleanup |
| `ticketbot/config.py` | `projects.json` + `agent.json` loading, channel → project |
| `ticketbot/agent.py` | tool definitions, Claude loop, cost log |
| `ticketbot/prompts/system.md` | the intake rules |
| `ticketbot/trackers/{base,trello,linear,memory}.py` | tracker contract, adapters, guard wrapper |
| `slack-manifest.yaml` | Slack app definition |

## Live status

First run 2026-11-06 against Linear team `THE` from `#eng-demo` (Ishwar's Slack app `A0CEW3VCW3H`): create, `add AC`, `move to Agent Ready`, refusal on an In Review issue with comment, and a top-level mention with no thread (lunch chatter in between was ignored). $0.04-0.11 per request on Opus 5.5, 17-44 s.

## Limits

- Reads links in the thread but does not fetch Granola/Paper content; `implement-card` does that later from the `Source:` / `Design:` lines.
- One Slack workspace, one bot token. Per-project tracker credentials come from the same `.env`.
- Mentions posted top-level (no thread) start from the 15 channel messages before them; the model can load up to 200 more via `load_earlier_messages`, then asks instead of guessing.
- Criteria can be added and removed (`remove_criteria`, exact or distinctive-substring match); labels are only ever added.
- Socket Mode = one running process. If it is down, mentions are dropped (Slack retries for a few minutes only).
