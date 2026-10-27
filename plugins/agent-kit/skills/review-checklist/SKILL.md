---
name: review-checklist
description: Team review checklist applied by the PR reviewer agent and by humans. Use when reviewing any pull request in this repo.
---

# Review checklist

Report only defects that would change behaviour, leak data, or break the build. Skip formatting and naming nits unless they change meaning. One inline comment per finding, anchored to the line; include the concrete failure scenario and a fix.

## Always check

1. **Secrets** — any string that looks like a key, token, password or signing secret hardcoded in source, tests, workflows or docs. Must come from env / GitHub secrets. Flag even if it looks like a demo value.
2. **None / null handling** — functions that dereference a value that can be `None`/`null` (lookups, optional fields, `dict.get`, nullable DB columns). Trace the caller: if any caller can pass a missing key, flag it.
3. **Input validation** — path/query params and request bodies used without validation or used to build SQL, shell commands, file paths or URLs.
4. **Error paths** — HTTP handlers that can raise an unhandled exception for a reachable input (should be 4xx, not 500).
5. **Tests** — changed behaviour without a test that exercises it. A test that only asserts the happy path for a bug fix is not enough; ask for the regression case.
6. **PR hygiene** — PR body has a `Card: https://trello.com/c/...` line; title follows `<type>: <summary>`; branch targets `temp-prod`, never `main`.

## Stack-specific

- **web/**: effects without cleanup or dependency array mistakes; fetches without error state; new user-visible flow without a Playwright spec; `any` types hiding a real shape.
- **api/**: Pydantic models for every request body; response shapes stable (no leaking internal fields); 404 vs 400 used correctly; no blocking I/O in async handlers.
- **docker / workflows**: unpinned images (`:latest`), secrets echoed to logs, `if:` conditions that silently skip required jobs.

## Output

Summary comment at the end: count of findings by severity (blocker / should-fix / nit), and an explicit "no blockers" line if none. Do not approve or request changes on behalf of a human.
