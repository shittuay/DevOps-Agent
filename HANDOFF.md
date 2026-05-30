# HANDOFF — Mobile Responsiveness

**Branch:** `claude/devops-agent-status-WEBmn`
**Date:** 2026-05-29
**Status:** Ready to merge into `main`

---

## Summary

Fixed mobile responsiveness across the app. The headline bug: the shared
`base.html` nav was `display:none` below 768px with no replacement, so **39
internal pages had zero navigation on mobile**. Added a hamburger drawer plus
responsive layout to the highest-traffic standalone pages.

## Commits on this branch (ahead of `main`)

| Commit | What |
|--------|------|
| `ed7f93e` | `fix(mobile): add hamburger nav to base.html — restore navigation on mobile` |
| `74831b2` | `fix(mobile): add responsive layout to high-traffic standalone pages` |

## Changes

**1. `templates/base.html` (affects 39 pages that extend it)**
- Added a `☰` hamburger toggle (`#mobileNavToggle`), shown only ≤768px.
- `.header-right` now becomes an opaque drop-down drawer when `.open` is set,
  instead of being hidden. Toggles to `✕`, closes on outside-click.
- Added horizontal-scroll fallback for wide `table`s.
- Bonus: `api_gateway/dashboard.html` and `admin/audit_logs.html` extend
  `base.html`, so they inherited the nav + table fixes automatically.

**2. Standalone pages — added a mobile `@media (max-width: 768px)` block**
- `templates/admin/dashboard.html`
- `templates/admin/users.html`
- `templates/scaling/dashboard.html`
- `templates/monitoring/rules.html`
- `templates/monitoring/alerts.html`
- `templates/templates.html`
- `templates/infrastructure/map.html`

Each block: stacks the flex header + wraps its nav, reduces container padding,
horizontally scrolls wide tables, and collapses fixed `1fr 1fr` form grids. The
topology map wraps its toolbar and hides the legend on small screens so filter
controls stay reachable.

## Verification

- Rendered templates and screenshotted in real Chromium at **375px** width.
- `base.html`: hamburger toggles the drawer, all nav links present, table
  scrolls horizontally. ✅
- `admin/dashboard.html`: header stacks, nav wraps, stat cards go
  single-column. ✅
- CSS/HTML only — no backend, model, or route changes. Low merge risk.

> Note: offline screenshots show a white background because the external theme
> stylesheet (which defines `--bg-primary` etc.) isn't served in the preview —
> render artifact only. In the app the drawer uses `var(--bg-primary)` (same as
> `body`), so it is opaque.

## Merge steps (desktop)

1. Open PR: `claude/devops-agent-status-WEBmn` → `main` (or merge directly).
2. No migrations, no env changes, no new dependencies.
3. Smoke-check on a phone / DevTools device mode: open any internal page (e.g.
   `/dashboard`, `/admin`), confirm the `☰` opens the nav drawer.

## Not done (out of scope — optional follow-up)

~58 lower-traffic standalone pages still lack `@media` rules (most of
`compliance/*`, `organizations/*`, `api_gateway/*` sub-pages, `chatops`,
`webhooks`, `analysis`, `approvals`). Most are small forms that degrade
gracefully. Note: pages already using `auto-fit minmax()` grids collapse
naturally and need no change.
