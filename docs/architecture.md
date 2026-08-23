# Duga architecture (M0 + M1)

Full rationale, data model, and roadmap live in `SPEC.md` at the repo root —
this doc is a short pointer into the current code, not a duplicate.

## Stack

- **Flask** app factory (`app/__init__.py`), server-rendered Jinja templates
  (`app/templates/`).
- **SQLAlchemy + Flask-Migrate** (`app/extensions.py`, `app/models/`,
  `migrations/`) over ToolsDB (MariaDB) in production, SQLite in tests.
  `app/config.py` prefers Toolforge's auto-provisioned `TOOL_TOOLSDB_USER`/
  `PASSWORD` envvars.
- **i18n**: `app/i18n.py` loads `i18n/<code>.json`. See `docs/i18n.md`.
- **No frontend build step**: `app/static/js/enhance.js` is hand-written
  vanilla JS, loaded as-is. No bundler, no framework (SPEC.md section 5,
  guardrail 3).
- **Deployment**: Toolforge Build Service, straight from GitHub `main`. See
  `docs/deployment-toolforge.md`.

## Request flow (web app)

Every route is a plain `GET` rendering a template; nothing on the web side
touches WDQS or the Wikidata API directly (SPEC.md section 4: no
request-path SPARQL) -- that only happens in `jobs/`:

- `GET /` — language picker (`app/templates/index.html`)
- `GET /<lang>/` — per-language overview stub, 404s for an unknown language
- `GET /about` — name/licence blurb
- `GET /health` — JSON `{"status": "ok"}` for monitoring

`app/i18n.py`'s `resolve_interface_lang()` runs in a `before_request` hook
and is exposed to every template via a context processor (`_()`, `autonym()`,
`available_languages`, `interface_lang`).

## Jobs (M1)

Standalone scripts, run via Toolforge's jobs framework, never via a web
request (SPEC.md section 4 -- "the web app only reads"):

- `jobs/scope_fetch.py` — fetches the on-wiki scope definition page (see
  `docs/scope-definition.md`), versions it into `scope_version`/`scope_rule`.
  Never auto-activates a new version.
- `jobs/topic_refresh.py` — resolves the *active* scope_version's rules to
  Wikidata items via WDQS, writes `topic`/`topic_rule`. Statically refuses to
  run any rule that claims `requires_reference=True` without a
  `prov:wasDerivedFrom` pattern in its SPARQL (SPEC.md section 3, S2) --
  this is enforced in code, not trusted from the on-wiki flag.
- `jobs/wikimedia_api.py` — the only code that talks to the Wikidata action
  API / WDQS. Both jobs are read-only against Wikimedia; no write path exists
  before M6.
- `scripts/activate_scope_version.py` — the operator action that promotes a
  fetched scope_version to active. A plain CLI, not a web endpoint: there's
  no auth'd admin UI until M4.

Both jobs are idempotent (SPEC.md guardrail 8): re-running `scope_fetch` for
an already-stored revision is a no-op; `topic_refresh` fully replaces
`topic_rule` rows for the active `scope_version_id` each run, while `topic`
rows persist (`first_seen` fixed, `last_seen` advances, `suppressed` never
touched by a job).

## What's deliberately not here yet

Per the milestone table (SPEC.md section 14): no detectors, no `gap` table,
no OAuth, no writes to Wikidata. M2 is the first slice that shows a gap list
to a visitor; M1 stops at a populated, silent `topic` table.
