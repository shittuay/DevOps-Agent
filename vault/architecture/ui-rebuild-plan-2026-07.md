---
date: 2026-07-16
type: rationale
tags: [ui, ux, templates, rebuild]
---

# UI rebuild plan (from the 2026-07-16 Playwright audit)

Full-app screenshot audit (20 pages, desktop + mobile, via Playwright against
localhost) found the marketing pages strong but the logged-in app fragmented.
Screenshots archived in the session scratchpad; findings summarized here.

**Root cause:** `templates/base.html` (unified header, Syne/Plex Mono/Outfit
type system, theme.css, mobile nav, shared components) exists and 40 newer
templates extend it — but the highest-traffic pages predate it and each built
its own header/nav/fonts: `index.html` (chat), `dashboard.html`,
`incidents/dashboard.html`, `optimization/prevention.html`,
`settings/skills.html`, `settings.html`, `infrastructure/map.html`.

## Findings by priority
1. **Fragmented nav** — every legacy page has a different header; some drop the
   logo entirely. Fix = migrate onto base.html, not build anything new.
2. **Typography split** — legacy app pages use a rounded font that fights the
   terminal brand; base.html already carries the correct marketing type system.
3. **Raster emoji as UI icons** (chat cards, map, 2FA, docs, base.html nav
   itself). Base loads Font Awesome — use it consistently.
4. **Copy bugs** — chat card says "36+ DevOps tools" vs the canonical 745;
   skills empty state shows dev instructions ("skills/ directory … .md files").
5. **Floating widget clutter** — free-floating theme-toggle pill overlaps
   content; mail FAB sits on the chat composer.
6. **Mobile chat** — cards clip under composer; placeholder overflows.
7. **Landing scroll-reveal** — sections invisible without scroll events (JS
   off / reduced-motion / crawlers see a blank page below the hero).
8. **Self-host API-key gate** leaks `config/.env` guidance on `/chat` if the
   server key is missing — SaaS fallback should be a generic error state.

## PR sequence
- **PR 1 (this branch):** migrate `dashboard.html`, `incidents/dashboard.html`,
  `optimization/prevention.html`, `settings/skills.html` to extend base.html;
  copy fixes (#4); replace base.html nav emoji with Font Awesome.
- **PR 2:** chat header alignment (index.html is 4,243 lines — its own PR),
  mobile composer fixes, FAB/theme-toggle placement.
- **PR 3:** `settings.html` (2,017 lines) — split the mega-page into sections
  while migrating; `infrastructure/map.html` needs a full-bleed variant of
  base (add a block for uncontained main).
- **PR 4:** landing reveal robustness + docs button contrast + login/register
  polish.

Verification loop: Playwright screenshots against localhost:5001 (AirPlay owns
port 5000 on this Mac — see [[user-profile]] gotchas), SQLite dev DB, dummy
`ANTHROPIC_API_KEY`.
