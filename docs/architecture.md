# Duga architecture (M0 + M1 + M2)

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

## Content vs. interface languages

Two independent language concepts share this codebase (SPEC.md section 13):

- **Interface languages** (`i18n/*.json`: en, sr, fr) — which language the
  UI chrome is translated into. Chosen via `?uselang=`, a cookie, or
  Accept-Language; `app/i18n.py`.
- **Content languages** (`language` table, `seeded = true`: sr, fr) — which
  Wikimedia languages Duga tracks gaps for. A much larger, separately-grown
  set; `app/models/reference.py`.

They happen to overlap right now (both sets include sr/fr) but are read from
different places on purpose, so adding a content language never requires an
interface translation to exist first, or vice versa.

## Request flow (web app)

Every route is a plain `GET` rendering a template; nothing on the web side
touches WDQS or the Wikidata API directly (SPEC.md section 4: no
request-path SPARQL) -- that only happens in `jobs/`:

- `GET /` — language picker, from the `language` table (`app/templates/index.html`)
- `GET /<lang>/` — per-language overview: gap count, detector staleness, or
  a placeholder if nothing has run yet. 404s for an unseeded language.
- `GET /<lang>/gaps` — the gap list for that language, filterable by
  `?project=`/`?type=`, paginated (`GAPS_PAGE_SIZE` = 50)
- `GET /about` — name/licence blurb
- `GET /health` — JSON `{"status": "ok"}` for monitoring

`app/i18n.py`'s `resolve_interface_lang()` runs in a `before_request` hook
and is exposed to every template via a context processor (`_()`, `autonym()`,
`available_languages`, `interface_lang`).

## Jobs (M1 + M2)

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
- `jobs/wp_no_article.py` — the first detector (v0.1 table, maturity
  `stable`): for every non-suppressed topic and every seeded language,
  checks (via batched `wbgetentities`, 50 QIDs/call) whether a Wikipedia
  article exists; writes `gap` rows for the ones that don't, plus a
  self-registered `detector` row recording `last_run_at`/`last_status`.
  Collects results fully in memory before writing anything, so a failed run
  never leaves `gap` half-updated -- it only ever fully-replaces-or-leaves
  untouched.
- `jobs/wikimedia_api.py` — the only code that talks to the Wikidata action
  API / WDQS. All jobs are read-only against Wikimedia; no write path exists
  before M6.
- `scripts/activate_scope_version.py` — the operator action that promotes a
  fetched scope_version to active. A plain CLI, not a web endpoint: there's
  no auth'd admin UI until M4.

All jobs are idempotent (SPEC.md guardrail 8): re-running `scope_fetch` for
an already-stored revision is a no-op; `topic_refresh` and `wp_no_article`
fully replace their own rows each run (`topic_rule` for the active
scope_version_id; `gap` per detector_key + language_code), while `topic`
rows persist (`first_seen` fixed, `last_seen` advances, `suppressed` never
touched by a job).

## A scope note worth re-checking later

`jobs/wp_no_article.py` reads SPEC.md S7 ("is_living topics excluded from
experimental detectors... and any bulk/batch surface") as applying to batch
*editing* (out of scope for v0.1 per section 9), not a read-only stable-
maturity gap list -- since the topic's in-scope status already passed the
S2 sourced-reference bar, listing "no article yet" adds no new information
about the person. Flag this interpretation if it should be revisited.

## What's deliberately not here yet

Per the milestone table (SPEC.md section 14): no `gap_override` (M3), no
suppression UI (M3), no OAuth (M4), no writes to Wikidata (M6). M2 is the
first slice a visitor can actually use end to end: pick a language, see
real gaps, click through to fix one.
