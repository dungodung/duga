# Duga architecture (M0)

Full rationale, data model, and roadmap live in `SPEC.md` at the repo root —
this doc is a short pointer into the current code, not a duplicate.

## Stack (M0 slice)

- **Flask** app factory (`app/__init__.py`), server-rendered Jinja templates
  (`app/templates/`). No ORM, no database yet — those land with M1's
  `scope_version`/`topic` tables (SPEC.md section 7).
- **i18n**: `app/i18n.py` loads `i18n/<code>.json`. See `docs/i18n.md`.
- **No frontend build step**: `app/static/js/enhance.js` is hand-written
  vanilla JS, loaded as-is. No bundler, no framework (SPEC.md section 5,
  guardrail 3).
- **Deployment**: Toolforge Build Service, straight from GitHub `main`. See
  `docs/deployment-toolforge.md`.

## Request flow (M0)

Every route is a plain `GET` rendering a template; nothing touches a
database or an external API yet:

- `GET /` — language picker (`app/templates/index.html`)
- `GET /<lang>/` — per-language overview stub, 404s for an unknown language
- `GET /about` — name/licence blurb
- `GET /health` — JSON `{"status": "ok"}` for monitoring

`app/i18n.py`'s `resolve_interface_lang()` runs in a `before_request` hook
and is exposed to every template via a context processor (`_()`, `autonym()`,
`available_languages`, `interface_lang`).

## What's deliberately not here yet

Per the milestone table (SPEC.md section 14): no ToolsDB, no scheduled jobs,
no scope definition fetch, no detectors, no OAuth, no writes. M0 exists to
prove the skeleton deploys and the i18n pipeline works end to end — see
"Conference-critical path: M0 → M2 → M5" in SPEC.md section 14.
