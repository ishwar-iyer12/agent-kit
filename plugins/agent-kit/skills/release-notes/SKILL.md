---
name: release-notes
description: Summarise merged PRs since the last release tag into Slack-ready release notes. Use before cutting a release or for the weekly digest.
---

# release-notes

1. Find the range: `git fetch --tags && last=$(git describe --tags --abbrev=0 origin/main 2>/dev/null || echo "")`. If no tag, use the last 7 days.
2. List merged PRs: `gh pr list --state merged --base temp-prod --search "merged:>=<date>" --json number,title,url,labels,author,body --limit 100`.
3. Group by Conventional Commit type from the title: **Features** (feat), **Fixes** (fix), **Internal** (chore/refactor/ci/docs). Within a group, order by client label (`client:*`) first.
4. One line per PR: `• <title> (<#number>) — <card short link if the body has a Card: line>`.
5. Prefix with a two-line summary a non-engineer can read. Suffix with "Staging: <url>" if `STAGING_HOST` is known and "Known gaps:" for any PR labeled `[blocked]` or with failing checks.
6. Output as Slack mrkdwn (use `*bold*`, `•`, `<url|text>`). Do not post it yourself unless asked; print it.
