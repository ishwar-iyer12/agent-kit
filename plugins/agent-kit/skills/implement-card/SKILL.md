---
name: implement-card
description: Implement a Trello card or Linear issue end to end — read the spec (Slack/Granola/Paper), branch from the project's base branch, code, test, screenshot, open a PR, update the tracker. Use when given a card URL, Linear issue key or short id.
---

# implement-card

Input: a Trello card URL (`https://trello.com/c/<short>`), a Linear issue key (`TL-123`) or URL. Runs unattended, so never stop to ask a question that the standing answers in your prompt already cover; if something is genuinely blocking, comment the question on the card/issue, prefix the PR title with `[blocked]`, and stop.

Read `agent.json` at the repo root first. It tells you the tracker, base branch, branch prefix, test commands, Paper file id and export dir. Read `CLAUDE.md` for everything else.

## 1. Gather the spec

1. Fetch the card/issue: title, description, checklist (Trello) or description bullets (Linear), labels, comments, attachments.
   - Trello: MCP connector if present, else REST `GET https://api.trello.com/1/cards/<short>?fields=name,desc,labels,url,shortLink&checklists=all&actions=commentCard&attachments=true&key=$TRELLO_KEY&token=$TRELLO_TOKEN`.
   - Linear: MCP connector if present, else GraphQL `POST https://api.linear.app/graphql` with header `Authorization: $LINEAR_API_KEY`, query `issue(id:"<key>"){ id identifier title description labels{nodes{name}} comments{nodes{body}} attachments{nodes{url title}} state{name} }`.
2. Follow the `Source:` link. A Slack permalink → fetch the thread via the Slack connector. A Granola link → fetch the transcript via the Granola connector. That transcript is the primary spec; the card is the summary. Quote the deciding sentence in the PR body.
3. If there is a `Design:` link (Paper artboard) and the Paper MCP is available in this session:
   - `get_basic_info` on the file, `find_nodes` / `get_tree_summary` to locate the artboard named in the link.
   - `get_jsx` for the artboard and `get_computed_styles` for any node whose exact values matter; `get_tokens` for the file's design tokens; `get_screenshot` of the artboard.
   - Write them under `<design.exportDir>/<card-id>/` as `design.jsx`, `tokens.json`, `expected.png`, plus `README.md` naming the Paper file and artboard. Commit them in the PR: the reviewer in CI has no Paper access and compares your UI against this export.
   - If the Paper MCP is not available (cloud session, CI), say so in the PR body under "Design" and implement from the card text only. Never label UI cards `cloud` for this reason.
4. Acceptance criteria = the checklist / bullets. None present → derive 2–4 testable criteria from the description and the source, post them as a comment, continue.

## 2. Implement

1. `git fetch origin && git switch -c <branchPrefix><id>-<slug> origin/<baseBranch>` (Trello: short id; Linear: the lowercase issue key, e.g. `agent/tl-123-owner-domain`). Slug = 2–4 lowercase words from the title.
2. Smallest change that satisfies every criterion. Match surrounding style. If `tokens.json` was exported, use the token values (colors, spacing, type) rather than hand-picked ones; `/agent-kit:design-tokens` syncs them into the repo's token file if the project has one.
3. Tests next to the change. New user-visible flow → Playwright spec (`/agent-kit:e2e`).
4. Run the project's test commands from `agent.json` (`test.web`, `test.api`, `test.e2e` when relevant). Fix failures. Never skip or delete tests to get green.
5. UI change → take a Playwright screenshot of the result (`page.screenshot({ path: '<exportDir>/<card-id>/actual.png', fullPage: true })` in a throwaway spec or via the Playwright MCP) and commit it beside `expected.png`.

## 3. Ship

1. Conventional Commit. Body explains why.
2. `git push -u origin HEAD`.
3. `gh pr create --base <baseBranch> --fill`, then set the body to the repo's PR template: what/why, how tested, **Design** section with `expected.png` and `actual.png` side by side when present, and the line `Card: <trello url>` or `Issue: <linear url>`.
4. Tracker update: comment the PR URL + one line; move to in-review (Trello list from `agent.json.trello.lists.inReview`; Linear state from `agent.json.linear.states.inReview` via `issueUpdate`).
5. Append one line to `overnight-report-<date>.md` at the repo root if it exists (the runner creates it): `- [<id>] <title> — <status> — <PR url>`.
6. Report back: id, branch, PR URL, tests run, design export present or not, anything left for a human.

## Guard rails

- Never push to the base branch or the release branch directly. Never force-push.
- Never commit `.env`, keys, tokens. New env var → `.env.example` + mention in PR.
- One card, one PR. Unrelated findings → comment on the card, do not fix.
- Secrets or credentials missing → stop, comment on the card, `[blocked]` prefix.
