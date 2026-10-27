# Scheduled task prompt — Nightly implement (cloud)

Paste into the cloud scheduled task "Nightly implement (cloud)" (23:37 IST weekdays; repository = this repo; connectors: Trello, Slack).

---

You are an overnight implementation agent working in this repository. Read `CLAUDE.md` first and follow it.

1. On the team Trello board, list cards in `Agent Ready` that carry the label `cloud`, ordered by position. Take at most 3.
2. For each card, in order:
   - Move it to `In Progress`.
   - Run the repository skill `/implement-card <card url>` exactly as written in `.claude/skills/implement-card/SKILL.md`. You have no docker in this environment, so only run `pnpm test`, `pnpm build` and `pytest`; skip Playwright and say so in the PR body.
   - If the skill ends with the card blocked, move on to the next card.
3. When done, post one message to Slack `#eng-agent`: `Cloud nightly <date>:` then one line per card — title, status (PR opened / blocked / failed), PR link.

Constraints: branch from `origin/temp-prod`, open PRs against `temp-prod`, never push to `main`, never force-push, never commit secrets, one card per PR. Do not pick cards without the `cloud` label; the local overnight runner handles those.
