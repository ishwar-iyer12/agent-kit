---
name: design-tokens
description: Sync design tokens from the project's Paper file into the repo (tokens.json + CSS custom properties) so code and reviewer use the same values. Use when a UI card references Paper, when tokens changed, or when asked to "sync tokens".
---

# design-tokens

Paper is the source of truth for colors, spacing, type and radii. This skill copies them into the repo so that code, tests and the CI reviewer (which has no Paper access) all see the same values.

## Steps

1. Read `agent.json`: `design.paperFileId` (null → ask the user for the Paper file, or use the file they have open: `get_basic_info` with no id) and `design.exportDir` (default `design`).
2. Paper MCP: `get_tokens` on the file. If the response groups tokens by collection/mode, keep every mode (e.g. light/dark).
3. Write `<exportDir>/tokens.json` verbatim (stable key order, 2-space indent) with a top-level `"source": { "paperFileId": ..., "exportedAt": "<ISO date>" }`.
4. Generate `<exportDir>/tokens.css`:
   - `:root { --<group>-<name>: <value>; }` for the default mode.
   - If a dark mode exists: the same tokens under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }` and `:root[data-theme="dark"] { ... }`.
   - Token name → kebab-case; colors as the value Paper gives (hex/rgba); dimensions in px unless Paper says otherwise.
5. If the project has an existing token file (look for `tokens.css`, `theme.ts`, `tailwind.config.*` `theme.extend`), update it from `tokens.json` instead of introducing a second source; keep its format. Do not rename existing tokens; add a mapping comment where names differ.
6. Run the project's web tests/build from `agent.json.test.web`. Fix type errors caused by renamed tokens.
7. Commit as `chore(design): sync tokens from Paper <date>` and mention the diff summary (added / changed / removed token counts) in the PR body if a PR is open.

## Rules

- Never hand-edit `tokens.json`; it is generated. Hand edits go in Paper.
- Never commit screenshots or JSX exports from this skill; `implement-card` does that per card.
- If `get_tokens` fails or the Paper MCP is absent, stop and say so. Do not invent values.
