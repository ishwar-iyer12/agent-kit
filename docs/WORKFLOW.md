# Agent-first engineering workflow

How we work from now on. Goal: agents do the typing 10+ hours a day, engineers spend their time on specs and review. Nothing below requires creating a ticket, a doc or a Trello card by hand.

## The pipeline

```
Slack thread / Granola call
        │  hourly cloud task "Intake triage" (reads Slack + Granola, writes Trello)
        ▼
Trello: Inbox → Needs Spec → Agent Ready → In Progress → In Review → Done
        │  23:00 weekdays: Orca automation runs scripts/agent/overnight.ps1
        │  (one Claude Code worker per card, each in its own git worktree)
        ▼
PR → temp-prod
        │  GitHub Actions: CI (vitest, pytest, Playwright) + Claude PR review (API credits)
        ▼
label `deploy-staging` or merge → staging EC2 → Slack #eng-agent gets the link, card gets a comment
        │
        ▼
Morning: review in Orca, `@claude fix …` on the PR for changes, merge, card → Done
```

## Roles

| Who | Does | Does not |
|---|---|---|
| Anyone (CEO, client-facing) | Says what's needed in Slack or on a recorded call | Create cards |
| Intake agent | Turns Slack/Granola into cards with acceptance criteria; asks one clarifying question in-thread when a spec is thin | Decide priority |
| Devang (product) | Orders `Agent Ready`, sets `P0–P2` / `client:*` labels, answers `Needs Spec` questions | Write tickets from scratch |
| Engineers | Morning: review PRs, merge, re-queue. Day: pair with agents on the hard cards. Evening: make sure `Agent Ready` has 3–5 well-specified cards for your name | Hand-write boilerplate, run deploys by hand |
| Overnight agents | Implement cards, tests, PRs | Touch `main`, change scope |
| Reviewer agent | Inline PR comments against `.claude/skills/review-checklist/SKILL.md` | Approve or merge |

## A card is "Agent Ready" when

- Title says the outcome, not the task ("Owners can see unowned metrics", not "Fix table").
- Description links the source (Slack permalink or Granola note) and names the affected layer (`web`, `api`, `cube`, `dbt`, `infra`).
- Checklist = acceptance criteria an agent can turn into tests. 2–5 items.
- Labels: client (`client:clevergear` …) if relevant; `cloud` if it needs no docker (SPA-only / pure Python) so the cloud nightly can also pick it up.
- Assigned to one engineer (the overnight runner only picks your own cards).

If any of this is missing the intake agent leaves it in `Needs Spec` and asks in the Slack thread.

## Daily rhythm (engineer)

**Evening (10 min)**
1. Open Trello. Make sure 3–5 cards in `Agent Ready` are assigned to you and actually ready (see above).
2. Laptop on, plugged in, power plan "never sleep". Orca open. (Or rely on the cloud nightly for `cloud`-labeled cards.)

**Morning (30–60 min)**
1. Read the overnight report in `#eng-agent` (or `overnight-report-<date>.md`).
2. In Orca → Agents feed: open each worktree, read the AI diff annotation, run the app if UI changed.
3. Read the reviewer agent's inline comments. For each PR:
   - Good → merge to `temp-prod`, card → `Done` (or `In Review` for product sign-off).
   - Needs changes → comment `@claude <what to change>` on the PR; the CI agent pushes a fix commit. Re-review.
   - Wrong direction → close PR, improve the card's criteria, back to `Agent Ready`.
4. Anything `[blocked]` → answer the question on the card, back to `Agent Ready`.

**During the day**
- Big or ambiguous work: drive it interactively in Orca (worktree per card, Claude Code as agent). Same skills apply (`/implement-card`).
- Need something small while away from the laptop: `@Claude` in a Slack channel thread → cloud session → "Create PR" button.

## Branching

- `temp-prod` = integration. `main` = release. Agents never touch `main`.
- `agent/<short>-<slug>` branches, one card per PR, PR body carries `Card: <url>`.
- Merge = squash. Delete branch on merge.

## Review standard

Agents review first, humans review second — but humans still read every diff before merge. Reviewer agent = `claude-sonnet-5-5` by default; add label `deep-review` to a PR for an Opus pass on anything touching auth, billing, tenancy or migrations.

## Escalation

- Agent stuck → it comments on the card and prefixes the PR `[blocked]`. Not Slack.
- Pipeline broken (CI red on `temp-prod`, deploy failing) → whoever sees it first posts in `#eng-agent` and `@Claude investigate <link>`.
- Usage: if Max usage > 80 % mid-week, drop `OVERNIGHT_MAX_CARDS` to 3 and move `cloud` cards to the API-key review path only.

## What we deliberately do not do

- No manual Trello cards, no status docs, no standup notes. If context exists in Slack or on a call, the agent reads it there.
- No direct deploys from feature branches. Staging comes from `temp-prod` or a labeled PR; prod from `main` via workflow.
- No private forks of this process per engineer. Change `CLAUDE.md` / the skills via PR like anything else.
