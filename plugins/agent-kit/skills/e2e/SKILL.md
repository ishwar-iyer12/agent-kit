---
name: e2e
description: Run or write Playwright end-to-end tests for the web app against a live API. Use when verifying a user-visible change or adding an e2e spec.
---

# e2e

## Run

```bash
# terminal 1 — API
cd api && .venv/Scripts/uvicorn app.main:app --port 8000      # Windows; use .venv/bin on Linux/macOS

# terminal 2 — tests (vite dev server is started by playwright.config.ts)
cd web && pnpm e2e
```

First time only: `pnpm e2e:install` (downloads Chromium). On failure open `web/playwright-report/index.html` or the trace zip in `web/test-results/`.

Full-stack alternative: `docker compose up --build` then run specs with `baseURL=http://localhost:8080` (`PLAYWRIGHT_BASE_URL` is not wired yet; edit `use.baseURL` locally if needed).

## Write

- Specs live in `web/e2e/*.spec.ts`. One file per user flow.
- Select by role / test id, never by CSS class. Add `data-testid` to the component when no accessible role fits.
- Assert on visible outcome (text, table rows, URL), not on network calls, except for the API health probe.
- Keep specs independent: no shared state between tests; the API store is in-memory and resets on restart, so specs that mutate must create their own metric keys (prefix `e2e_`).
- Deterministic data only — the demo tenants/metrics in `api/app/metrics.py` are the fixtures.

## CI

`.github/workflows/ci.yml` job `e2e` starts uvicorn in the background, installs Chromium, runs `pnpm e2e`, and uploads `playwright-report` + `test-results` on failure.
