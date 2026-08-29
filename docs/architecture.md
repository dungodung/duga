# Duga architecture (M0 + M1 + M2 + M3 + M4 + M5)

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
- **Content languages** (`language` table, `seeded = true`) — which
  Wikimedia languages Duga tracks gaps for. A much larger, separately-grown
  set; `app/models/reference.py`. Currently eleven: the ten largest
  Wikipedias by article count (en, ceb, de, fr, sv, nl, es, ru, it, pl —
  measured against each wiki's own `meta=siteinfo`, seeded by migration
  `b3f1c07a5e92`) plus sr, which predates them and stays because it is the
  conference language.

They overlap only partly (en/sr/fr are both), and are read from different
places on purpose, so adding a content language never requires an interface
translation to exist first, or vice versa — you can browse German gaps with
a Serbian interface, and nobody has translated Duga's chrome into German.

Two things worth knowing about that top-ten list. It ranks by **article
count**, which is not the same as ranking by community: `ceb` (6.1M
articles, ~230 active users) and to a lesser extent `sv` are largely
bot-generated, so their gap lists are long and their pool of people to fix
anything is small. And every added language multiplies detector work —
each detector loops languages × topics — so the daily job window and the
`gap` table both grow roughly linearly with this list. Swapping the ranking
for something community-weighted (active users, or a hand-picked set) is a
one-line change to a migration, not a code change.

## Request flow (web app)

Every route is a plain `GET` rendering a template; nothing on the web side
touches WDQS or the Wikidata API directly (SPEC.md section 4: no
request-path SPARQL) -- that only happens in `jobs/`:

- `GET /` — language picker, from the `language` table (`app/templates/index.html`)
- `GET /<lang>/` — per-language overview: gap count, detector staleness, or
  a placeholder if nothing has run yet. 404s for an unseeded language.
- `GET /<lang>/gaps` — the gap list for that language, filterable by
  `?project=`/`?type=`/`?maturity=` (SPEC.md section 12's three filters,
  offered as one plain no-JS `GET` form above the list), paginated
  (`GAPS_PAGE_SIZE` = 50). Every gap query goes through
  `_visible_gaps_query()`, which excludes a gap if its topic is
  suppressed or if a `gap_override` row exists for that exact
  (topic, language, project, gap_type) -- SPEC.md S4 ("filtered at query
  time in every code path") and guardrail 5. See "Gap list filters and
  staleness" below for the two non-obvious parts.
- `GET /about` — name/licence blurb
- `GET /health` — JSON `{"status": "ok"}` for monitoring
- `GET /login`, `GET /oauth/callback`, `POST /logout` — Wikimedia OAuth 2.0
  (see below and `docs/oauth-setup.md`)
- `GET /account`, `POST /account/attribution` — a contributor's own account
  page and the public-attribution opt-out toggle
- `GET /<lang>/vocabulary`, `POST /<lang>/vocabulary/add` — the vocabulary
  list for a language, with the add-a-term form inline (see below)
- `GET /<lang>/vocabulary/<id>`, `POST /term/<id>/evidence`,
  `POST /term/<id>/assert` — a term's detail page, plus adding a citation
  and agreeing/disagreeing with it
- `GET /concept/<id>` — one concept's terms across every language

`app/i18n.py`'s `resolve_interface_lang()` runs in a `before_request` hook
and is exposed to every template via a context processor (`_()`, `autonym()`,
`available_languages`, `interface_lang`); `contributor` (the logged-in
`Contributor` row, or `None`) is injected the same way, from
`app/blueprints/auth/routes.py:current_contributor()`.

## Login (M4)

SPEC.md section 9: "No Duga-local passwords, ever." `app/blueprints/auth/`
implements the Wikimedia OAuth 2.0 Authorization Code flow:

- `oauth_client.py` — the four HTTP calls (authorize URL, token exchange,
  refresh, profile fetch) against `meta.wikimedia.org/w/rest.php/oauth2/*`.
- `routes.py` — `/login` builds a random `state`, stores it in the session,
  and redirects; `/oauth/callback` validates that `state` (CSRF protection)
  before exchanging anything, then upserts a `Contributor` row keyed by the
  profile's `username`. A brand-new contributor is routed through
  `/account` first, not straight to `?next=`, so the public-attribution
  opt-out (defaults on, per section 9) is seen prominently at first login
  rather than left buried in a settings page nobody visits.
- Every contributor-affecting write goes through `app/audit.py:log()` into
  `audit_log` (guardrail 11) -- but only the writes that actually change
  something: a new contributor row, or an attribution preference that
  actually flipped. A routine returning login updates `last_seen_at` without
  an audit row; auditing every visit would make that table noise, not a
  record of decisions.
- If `DUGA_OAUTH_CLIENT_ID` is unset, `/login` renders a plain "not
  configured" page (503) instead of building a broken authorize URL --
  deploying before the OAuth consumer is registered is safe.

As of M4, access/refresh tokens were used once at login and never
persisted -- M6's preview-then-confirm write flow (see below) needed that
reversed, since it spans two separate HTTP requests and the second one
needs a token to act with. See the M6 section for what changed and why.

## Vocabulary (M5)

The conference-seeding flow (SPEC.md section 12: "must be completable on a
phone in under 60 seconds"). `app/blueprints/vocabulary/`:

- The add-a-term form lives inline on `/<lang>/vocabulary` (no separate page
  to navigate to first) -- one text field for the concept name (a native
  `<datalist>` suggests existing concepts, zero JS, degrades to a plain text
  field), one for the word, a register dropdown, an optional note. Submitting
  finds-or-creates the `Concept` by case-insensitive `local_label` match,
  then creates the `Term` -- or, if that exact (concept, language,
  written_form) already exists, flashes a message and links to it instead
  of creating a duplicate (the `UniqueConstraint` backs this up either way).
- `app/vocab_grading.py:recompute_evidence_grade()` -- SPEC.md section 8:
  documented > organisational > community > single_report, recomputed
  (never trusted from a typed value) whenever `term_evidence` or
  `term_assertion` rows change, and stored on `term.evidence_grade` so list
  views don't need a join+count per row. `community` requires
  `DUGA_COMMUNITY_ASSERTION_THRESHOLD` (default 3) distinct *agreeing*
  assertions; disagreeing ones don't count toward it, and a single
  `documented`/`organisational` citation outranks any number of assertions.
- `app/attribution.py:public_name()` -- SPEC.md S5: every place a
  `created_by`/`added_by` username would otherwise be printed goes through
  this first. A username with no matching `Contributor` row, or one that
  opted out, renders as anonymous -- "show less" (guardrail 12) is the
  default for anything not confirmed public, not the exception.
- Suppression follows the same pattern as `gap`'s `_visible_gaps_query()`:
  `_visible_terms_query()` excludes a term if either it or its concept is
  suppressed (SPEC.md S4 explicitly covers "topic or term"). Unlike `topic`,
  `concept`/`term` have only a bare `suppressed` boolean in the schema (no
  reason/by/at columns) -- `scripts/suppress_vocabulary.py` logs the reason
  and actor to `audit_log` instead, which exists as of M4.

## Writing to Wikidata (M6)

SPEC.md S1: "Duga never writes an identity statement (P21/P91/etc.) to
Wikidata, full stop." `app/wikidata_write.py` is the *only* code in the
codebase that can write to Wikimedia, and it is structurally narrow rather
than merely allowlist-checked at runtime: the module contains exactly two
functions, `set_label()` and `set_description()` -- there is no generic
"set claim" function anywhere in Duga, so a P21/P91 write isn't just
disallowed, it's not expressible through this code path at all.
`EDITABLE_GAP_TYPES` maps `no_label`/`no_description` gaps to `label`/
`description` edit kinds; no other gap type is editable.

- `app/blueprints/write/routes.py` (`GET`/`POST /gap/<id>/edit`) --
  preview-then-confirm: the first `POST` (no `confirmed` field) re-renders
  the form with the exact value that would be written and does not touch
  Wikidata; only a second `POST` with `confirmed=1` performs the edit. This
  is the reason token persistence (below) exists -- the confirm step is a
  separate HTTP request from the one that authenticated it.
- SPEC.md S8 ("global write kill switch checked immediately before every
  write") — `DUGA_WRITES_ENABLED` is read fresh at the top of the confirm
  handler, not cached; `DUGA_MAX_WRITES_PER_HOUR_PER_USER` and
  `_GLOBAL` are enforced the same way, counting recent `wiki_edit` rows.
- Token persistence: `app/token_crypto.py` (Fernet symmetric encryption,
  key from `DUGA_TOKEN_ENCRYPTION_KEY`) and `app/token_store.py`
  (`save_tokens()`/`get_valid_access_token()`/`TokenUnavailable`) hold one
  encrypted access+refresh token per contributor in `contributor_token`,
  refreshing transparently via `oauth_client.refresh_access_token()` when
  the access token is stale. If no usable token exists (never logged in
  since this shipped, or the refresh itself fails), the write route redirects
  to `/login` rather than failing -- SPEC.md guardrail 9, "fail loudly,
  never serve stale as fresh," applies to a stuck write too.
- Every attempt -- success or failure -- is logged to `audit_log`
  (`wiki_edit_attempt` before, `wiki_edit_success`/`wiki_edit_failed` after)
  and recorded as a `wiki_edit` row (guardrail 11). A successful edit is
  attributed to the contributor's own Wikimedia account, exactly like any
  other Wikidata edit -- Duga is not a bot account making the edit on their
  behalf, the OAuth token *is* their account.
- `app/wikidata_lookup.py` also exists (see M7 below) but performs no
  writes -- it's a single read-only `wbgetentities` existence check.

## Promoting local vocabulary upstream (M7)

SPEC.md section 10's promotion path: `local -> proposed -> upstream`. This
only ever *links* an existing local `Concept`/`Term` to something that
already exists on Wikidata/Wikidata Lexemes -- it never creates a new item
or Lexeme there. (SPEC.md section 9's write allowlist for v0.1 is labels/
descriptions/aliases now, lexeme senses/forms "post-v0.1"; item/Lexeme
*creation* is never listed at all, at any stage.)

- `app/blueprints/vocabulary/routes.py`: `propose_concept`/`propose_term`
  move a `local` row to `proposed` (a pure lifecycle flip, no external
  call). `link_concept_upstream`/`link_term_upstream` move a `proposed` row
  to `upstream`, but only after: the submitted QID/Lexeme ID matches the
  expected format (`QID_PATTERN`/`LEXEME_PATTERN`), a concept's QID isn't
  already claimed by a different concept (the `unique=True` column backs
  this up), and -- the actual gate -- `app/wikidata_lookup.py:entity_exists()`
  confirms live that the ID exists on Wikidata. A Sense ID, if given, must
  be prefixed by its Lexeme ID (`L123-S1` under `L123`), since a mismatched
  pair would silently link to the wrong sense.
- Each stage transition is logged to `audit_log`
  (`propose_concept`/`propose_term`/`link_concept_upstream`/
  `link_term_upstream`), same pattern as every other contributor action.
- The lifecycle sequence is enforced server-side on every route, not just
  hidden via the UI: proposing something already `proposed`/`upstream`, or
  linking something still `local`, is rejected with a flash message rather
  than silently no-opping.

## Jobs (M1 + M2 + M3)

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
- `jobs/wp_no_article.py`, `jobs/wd_no_label.py`, `jobs/wd_no_description.py`
  — the three v0.1 detectors (maturity `stable`), all sharing
  `jobs/detector_common.py`'s `run_presence_detector()` for the identical
  half of their control flow (guard clauses, releasing the DB connection
  before the slow API loop, atomic gap replacement, detector
  self-registration). Only each one's own `compute_gaps_for_language()`
  differs:
  - `wp_no_article` checks Wikipedia sitelink existence via batched
    `wbgetentities` (`jobs/wikimedia_api.py:get_entities_batch`, which asks
    for the content language *with* MediaWiki's fallback chain, plus an
    explicit English fallback, since it's only fetching a display label).
  - `wd_no_label`/`wd_no_description` check genuine per-language label/
    description presence via `get_raw_labels_and_descriptions`, which
    deliberately does *not* use the fallback chain -- a fallback-derived
    value would mask a real gap -- while still getting an English label for
    display in the same request.
- `jobs/wikimedia_api.py` — the only code that talks to the Wikidata action
  API / WDQS. All jobs are read-only against Wikimedia; no write path exists
  before M6.
- `scripts/activate_scope_version.py` — the operator action that promotes a
  fetched scope_version to active.
- `scripts/suppress_topic.py` — the operator action for SPEC.md S4
  ("suppression is absolute and immediate... requires no upstream edit and
  no justification beyond a logged reason"): sets/clears
  `topic.suppressed`/`suppressed_reason`/`suppressed_by`/`suppressed_at`.
  Refuses to suppress without `--reason`.
- `scripts/set_gap_override.py` — the operator action for a human decision
  on one specific gap (declined / not_applicable / done) -- SPEC.md section
  7 ("human decisions live separately so recomputation never destroys
  them"), guardrail 5.
- `scripts/suppress_vocabulary.py` — the same suppression mechanism as
  `suppress_topic.py`, for a `concept` or `term` instead (see the
  Vocabulary section above for why it logs to `audit_log` rather than
  dedicated columns).

None of these scripts are web endpoints -- there's still no UI for
suppression (topic/concept/term), so each stays a plain CLI an operator
runs by hand on Toolforge. `set_gap_override.py` remains the only way to
set a gap's status to `done` (self-service can't -- see the section below),
but `declined`/`not_applicable` now have a self-service equivalent.

All jobs are idempotent (SPEC.md guardrail 8): re-running `scope_fetch` for
an already-stored revision is a no-op; `topic_refresh` and the three
detectors fully replace their own rows each run (`topic_rule` for the
active scope_version_id; `gap` per detector_key + language_code), while
`topic` rows persist (`first_seen` fixed, `last_seen` advances, `suppressed`
never touched by a job) and `gap_override` rows are never touched by a
detector at all.

## Self-service gap overrides

SPEC.md section 12's `POST /gap/override` (`app/blueprints/main/routes.py:
override_gap`) -- any logged-in contributor can mark a specific gap
`declined` or `not_applicable` directly from the gap list, with an optional
one-line reason. Deliberately narrower than the operator CLI in one way:
self-service can only ever set `declined`/`not_applicable`, never `done` --
`done` stays `scripts/set_gap_override.py`-only, since M6's write path
already marks a gap done the moment it's actually fixed (by deleting the
`gap` row directly), so a self-service "mark done" button would only ever
be used to fake having fixed something.

- Writes only to `gap_override`, exactly like the CLI script (guardrail 5:
  a detector's next run can never see or touch this table). The lookup
  reuses `_visible_gaps_query()`, so a gap that's already suppressed,
  already overridden, or doesn't exist 404s -- the same gap can't be
  overridden twice through this endpoint.
- Logged to `audit_log` (`override_gap`, guardrail 11) with the full
  before-state gap identity and the decision, on top of the `set_by`/
  `set_at`/`reason` columns `gap_override` already carries.
- No self-service undo: once set, only an operator can clear it
  (`scripts/set_gap_override.py --clear`). This is a real, if narrow,
  reversibility gap worth revisiting if it turns out to matter in practice --
  flagged here rather than solved speculatively.

## Self-service suppression

`GET|POST /topic/<qid>/suppress` (`app/blueprints/main/routes.py`),
`GET|POST /concept/<id>/suppress` and `GET|POST /term/<id>/suppress`
(`app/blueprints/vocabulary/routes.py`). Any logged-in contributor can
suppress, the same bar as `POST /gap/override`.

SPEC.md's route list never asked for these, and for a while this was
deliberately CLI-only. What changed the reasoning is what S4 actually says:
suppression is "absolute and immediate... requires no upstream edit and no
justification beyond a logged reason". That is a description of a safety
valve, and putting an operator round-trip in front of the one action a
person most needs when something must disappear *now* was friction in the
wrong place. The CLIs remain (`scripts/suppress_topic.py`,
`scripts/suppress_vocabulary.py`) and are still the only way to *lift* a
suppression.

Design points, all of them consequences of it being a safety action rather
than an editing action:

- **Two steps, not a button.** A link opens a confirmation page
  (`app/templates/suppress_confirm.html`) that states the real blast radius
  -- every language, every visitor, not just the row it was clicked from --
  and only then posts. Same preview/confirm shape as every write path.
- **A reason is required**, unlike the optional one on gap overrides. S4
  asks for a logged reason; the confirmation page's wording is deliberately
  "why? (recorded)" rather than anything that reads like justifying yourself
  to a reviewer.
- **One-way.** There is no self-service un-suppress, only
  `scripts/suppress_*.py --unsuppress`. Making something reappear should
  cost more than making it disappear -- the same asymmetry the gap-override
  section above notes, but here it is the intended design rather than a
  flagged gap.
- **Where the reason is stored differs by kind.** `topic` has
  `suppressed_reason`/`_by`/`_at` columns; SPEC.md section 7 gives `concept`
  and `term` only a bare boolean, so for those the reason and actor live in
  `audit_log` alone. This mirrors the split `scripts/suppress_vocabulary.py`
  already made.
- The redirect target after suppressing is carried as an explicit `lang`
  field and validated against seeded languages, rather than read from
  `Referer` -- it can't be turned into an open redirect.

Suppressing a **concept** also hides every term under it, since
`_visible_terms_query()` joins `Concept` and filters both booleans. The
confirmation page says so in its own message rather than relying on the
reader to know the data model.

## Enabling a detector vs. promoting one

`scripts/promote_detector.py` is the other half of this pair, and it is
gated where the spec asks for a gate: it refuses to promote out of
`experimental` without at least two named reviewers (SPEC.md section 11's
"native speakers of at least two affected languages"), prints how many
living topics the promotion would newly expose, and requires `--yes`
before proceeding. Demotion back to `experimental` needs neither --
making the handling of living people stricter never needs a ceremony.
Reviewers and the S7 consequence are recorded in `audit_log`, so the
decision is auditable after the fact rather than remembered.


`scripts/set_detector_enabled.py` flips `detector.enabled` and nothing
else. These are two separate switches and conflating them would quietly
breach S7:

- `enabled` controls **visibility** -- `_visible_gaps_query()` hides gaps
  whose detector row says `enabled = False`.
- `maturity` controls **labelling**, and also whether living people are in
  scope at all: `jobs/detector_common.py` excludes `is_living` topics only
  while maturity is `experimental`. Promoting a detector to `beta`/`stable`
  therefore switches living people back on for it, which is exactly what
  SPEC.md section 11 reserves for a human decision "after review with
  native speakers of at least two affected languages".

So enabling an experimental detector is the cheap, reversible half: its
gaps become visible, every row still reads "experimental" in the gap list,
and S7 keeps holding. The script has no flag that can change maturity --
promotion needs a different tool and a different conversation.

## Post-v0.1 detectors (S1+)

SPEC.md section 11 lists further detectors to "ship behind
`maturity = 'experimental'`, disabled by default" once v0.1 is stable.
Three sitelink-presence detectors are in place so far, structurally
identical to `wp_no_article` (a sitelink is either present under a given
project family's dbname or it isn't) but for sister projects instead of
Wikipedia:

- `jobs/wiktionary_no_entry.py` (project `wiktionary`, gap type `no_entry`)
- `jobs/wikiquote_no_quotes.py` (project `wikiquote`, gap type `no_quotes`)
- `jobs/wikisource_no_text.py` (project `wikisource`, gap type `no_text`)

The shared dbname/compute logic lives in `jobs/sitelink_gap.py`
(`sitelink_dbname()`, `make_compute_fn()`) rather than being copied three
times; `wp_no_article.py` itself is untouched and keeps its own inline
version, since it's a stable v0.1 detector and there was no need to
refactor it for this.

Two pieces of shared detector infrastructure needed fixing before any
experimental detector could correctly satisfy the contract in SPEC.md
section 11:

- `jobs/detector_common.py:upsert_detector_row()` used to hardcode
  `enabled=True` on every newly-created `detector` row regardless of
  `maturity`, which would have shipped every new detector *enabled* by
  default -- the opposite of what the spec calls for. It now defaults
  `enabled=(maturity != "experimental")` on creation only; an operator
  flipping an existing row's `enabled` flag is never touched by a later
  run (`tests/jobs/test_detector_common.py`).
- `jobs/detector_common.py:run_presence_detector()` now excludes
  `topic.is_living` topics from the qid set it hands to `compute_fn` when
  `maturity == "experimental"` -- SPEC.md S7, enforced centrally here
  rather than trusted to each new detector file, the same reasoning as
  `wikidata_write.py` enforcing S1 structurally instead of via
  per-call-site discipline. Stable detectors (`wp_no_article`,
  `wd_no_label`, `wd_no_description`) are unaffected.
- `app/blueprints/main/routes.py:_visible_gaps_query()` now also hides a
  gap whose `detector` row exists and says `enabled=False`. This fails
  open: a gap seeded without a matching `detector` row (as most existing
  tests do, and as could happen operationally) is unaffected, only an
  *explicit* disabled flag hides anything.

Since `enabled` now defaults to `False` for these three, none show up on
any gap list yet even after their jobs run -- promoting one to visible is
`UPDATE detector SET enabled = TRUE WHERE detector_key = '...'` by an
operator, matching the spec's "promotion to beta/stable is a human
decision after review with native speakers of at least two affected
languages."

Their `project` rows (`wiktionary`, `wikiquote`, `wikisource`) are seeded
by migration `6255d6f3ff0b`, matching the pattern M2/M3 used for
`wikipedia`/`wikidata` -- though note the `project` table itself is
currently unread by any code path; it's bookkeeping only, kept in sync as
a matter of hygiene rather than because something depends on it.

Two Commons detectors are also in place, checking for claim presence
rather than sitelink presence:

- `jobs/commons_no_image.py` (project `commons`, gap type `no_image`,
  P18)
- `jobs/commons_no_category.py` (project `commons`, gap type
  `no_category`, P373)

These needed a new Wikimedia API helper --
`jobs/wikimedia_api.py:get_claims_batch()` -- since `get_entities_batch`
only ever fetches sitelinks/labels, not claims. Shared compute logic
lives in `jobs/claim_gap.py:make_compute_fn(property_id)`, structurally
identical to `jobs/sitelink_gap.py` but checking "does this item have any
statement for property X" instead of "does this item have a sitelink to
project Y." Both ship `maturity = 'experimental'`, so both already get
the `is_living` exclusion for free from `run_presence_detector` --
which also resolves SPEC.md section 16's open question ("whether
commons_no_image on living people is ever acceptable (probably not)") in
the cautious direction by construction, without needing a special case:
the exclusion isn't specific to this detector, it's what "experimental"
already means for every detector in this batch.

One property of both that's worth calling out: unlike a sitelink or a
label, "does Q42 have a P18 statement" doesn't depend on which language
you're asking from. The gap is still written once per tracked language
regardless, because gaps are always scoped per-language in this app (each
language's `/<lang>/gaps` is its own actionable page) -- so a Serbian and
a French gap list can each surface the same "no image yet" fact
independently, which is exactly what you'd want two different language
communities to be able to act on.

Their `project` row (`commons`) is seeded by migration
`4eaa3f76db75`.

Two more detectors, `jobs/vocab_no_term.py` and `jobs/vocab_no_evidence.py`
(project `vocabulary`, gap types `no_term`/`no_evidence`), are unlike every
other detector so far: they check Duga's own `concept`/`term` tables, not
Wikidata or a sister project. "Does the community have a word for this
here" is a different question from "does Wikidata have a label for this,"
and "has anyone sourced this word" has no Wikidata analogue at all.

- `vocab_no_term`: flags an in-scope topic with no visible local term at
  all in a tracked language. The "missing" check is one local query per
  language (no external API call needed for it); a Wikidata label is then
  fetched, via the existing `get_entities_batch`, only for the topics that
  turn out to be missing -- so the gap row can show a real name rather
  than a bare QID.
- `vocab_no_evidence`: flags a local term that exists but has zero
  `term_evidence` rows (SPEC.md section 8: evidence_grade only rises above
  `single_report` once at least one citation or community assertion
  exists -- this is the case where there isn't even one). No API call at
  all; the term's own written form is the label, since that's literally
  the thing that needs a source.

Both are purely local-DB detectors, which `run_presence_detector` already
supported without changes: `db.session.close()` before the compute loop
only releases the current connection, it doesn't stop a `compute_fn` from
issuing new queries afterwards -- SQLAlchemy just checks a fresh one back
out lazily.

**Scope decision, not an oversight:** a `concept` can be purely local
(`qid IS NULL` -- SPEC.md section 10's local -> proposed -> upstream
lifecycle), which doesn't fit `gap.topic_qid NOT NULL`. Both detectors
only cover concepts that already have a qid (i.e. are linked to a Topic
already in scope). A purely local concept/term with no Wikidata item
behind it yet -- arguably the case Duga's vocabulary feature exists for
in the first place -- isn't represented as a gap by either detector. This
was chosen over widening the `gap` schema (a nullable `topic_qid` plus a
`concept_id` column, or a second table entirely) to avoid a schema change
for two detectors that ship disabled by default; revisit if operator
review after promotion shows the qid-only slice isn't the useful part.

**Action URLs needed a signature change.** Every other detector's fix
destination lives on Wikidata and doesn't depend on which language's gap
list is showing it, so the shared `action_url_fn(qid)` was only ever
called with the qid. `vocab_no_term`'s destination is
`/<lang>/vocabulary` -- language-specific -- so `action_url_fn` now takes
`(qid, language_code)` everywhere (all eight existing detectors' action
url functions were updated to accept and ignore the new parameter).
`vocab_no_evidence` needed to go one step further still: its real
destination is one specific term's detail page, which `action_url_fn`
has no way to know. `jobs/detector_common.py:replace_gaps()` now checks
for `evidence["_action_url"]` and uses it in place of `action_url_fn`
when a compute_fn sets it, stripping the key before the evidence is
stored so it never leaks into what's displayed as evidence. Two small
template anchors support these: `id="add-term-form"` in
`vocabulary_list.html` and `id="add-evidence-form"` in `term_detail.html`.

**A concept can have more than one under-evidenced term in the same
language** (different written forms of one idea) -- the `gap` table has
no per-term column, only `(topic_qid, language_code, project_code,
gap_type)`, so `vocab_no_evidence` flags the pair if *any* visible term
lacks evidence, deterministically linking to the lowest-id such term.
Guardrail 12 ("when in doubt, show less") is about sensitive display
decisions, not about hiding an ordinary maintenance need, so surfacing
the gap rather than suppressing it was the deliberate choice here -- the
cost is that a second under-evidenced term for the same concept/language
doesn't get its own gap until the first one gets a citation.

Their `project` row (`vocabulary`, family `duga` since it isn't a real
Wikimedia sister project) is seeded by migration `c2669d54cd43`.

## Gap list filters and staleness

Two details of `/<lang>/gaps` are worth writing down, because both are
places where the obvious implementation would quietly contradict what the
page shows.

**Maturity is a detector property, not a gap column.** `?maturity=` is
therefore an `EXISTS` against the matching `detector` row, not a column
comparison on `gap`. That interacts with `_visible_gaps_query()`'s
deliberate fail-open behaviour: a gap whose `detector_key` has no
`detector` row at all is still listed, and is *labelled* experimental
(`UNREGISTERED_MATURITY`). So `?maturity=experimental` matches "detector
says experimental **or** no detector row" -- otherwise filtering by the
word printed on a row would make that row disappear. An unrecognised
maturity value matches no detector and so returns nothing, the same way an
unrecognised `?project=` already did.

The `<select>` options for project and type are built from the
*unfiltered* visible gaps in that language, so the form never offers a
choice that returns zero rows, and a visitor who filters into an empty
list still has every other option on screen to get back out with. Maturity
is a closed three-value set, so all three are always offered. Pagination
links are built with `url_for`, which drops `None`-valued arguments --
inactive filters simply aren't in the link, active ones survive paging.

**Stale detectors are surfaced here, not only on the language overview.**
SPEC.md section 11's detector contract says a failed detector "shows as
stale in the UI rather than silently serving old data as current", and the
gap list is where that old data actually gets served -- a visitor can land
on `/sr/gaps` directly without passing the overview page. The warning names
the affected detector (project + gap type), so it's clear which rows are in
doubt rather than casting suspicion over the whole list. It's shown for a
detector that is enabled, has actually run, and whose `last_status` isn't
`ok`: a detector that never ran can't have served anything stale, and a
disabled detector's gaps are already hidden entirely by
`_visible_gaps_query()`.

## Lexeme write-back (S1+)

SPEC.md section 9 lists Wikidata Lexemes, Forms, and Senses as writable
"post-v0.1," alongside the labels/descriptions M6 already ships. This adds
exactly one new write: adding a brand new **Sense** (a meaning, with a
short gloss) to a Lexeme that **already exists** -- never a new Lexeme,
never a Form, never a claim. That scope wasn't picked arbitrarily: it's
the one gap M7's promotion path (`docs/architecture.md`'s "Promoting
local vocabulary upstream" section above) leaves behind. `link_term_upstream`
lets a contributor link a local term to an existing Lexeme without
necessarily having (or being able to find) an existing Sense for that
specific meaning -- `sense_id` is optional there. A term stuck in that
state -- `lifecycle = 'upstream'`, `lexeme_id` set, `sense_id` still NULL
-- is exactly the "linked but not really captured yet" case this closes.

- `app/wikidata_write.py:add_sense()` -- the only new function, calling
  the Wikibase Lexeme extension's `wbladdsense` action (never
  `wbeditentity`), so there's no path through this code to editing
  anything on the Lexeme except adding a wholly new Sense. `sense`
  joins `label`/`description` in `ALLOWED_EDIT_KINDS` (guardrail 6's
  explicit allowlist).
- `GET`/`POST /term/<id>/add-sense` (`app/blueprints/write/routes.py`) --
  same shape as every other write in this app: two-step preview/confirm,
  the S8 kill switch re-checked immediately before the API call (not
  earlier), the same per-user/global hourly rate limit `_rate_limited()`
  already enforced, `wiki_edit` written before and after, `audit_log`
  entries for the attempt and the outcome. `_term_awaiting_sense_or_404()`
  is this flow's equivalent of the gap-edit path's `_editable_gap_or_404`:
  only a visible term (SPEC.md S4 -- reuses `vocab.routes._get_visible_term_or_404`)
  in exactly the "linked, no sense yet" state is reachable.
- On success, `term.sense_id` is set to the real id Wikidata returned
  (never guessed locally), and `term.upstream_ref` is updated to point at
  it -- the same preference `link_term_upstream` itself gives a sense id
  over a bare lexeme id.
- Surfaced on `term_detail.html` as an "Add a sense to this Lexeme" link,
  shown only when the term is actually in that state -- there's no
  separate feature flag beyond that natural gating plus the existing
  `DUGA_WRITES_ENABLED` kill switch and rate limits, since every M6-level
  safety property already applies identically here.

## Impact scoring (S1+)

SPEC.md section 16 explicitly deferred this: "Impact scoring formula --
deferred; must satisfy S6." S6 itself is specific about what that means:
"Impact scoring ranks *topics within a language*. It never ranks
languages against each other, and no view may be constructed that does
so implicitly (e.g. sorting languages by gap count)." The design below
was worked out with the tool's operator rather than built unilaterally,
given the spec's own instruction to stop and think here.

`jobs/impact_score.py` is a standalone job -- not a detector; it owns no
`gap_type` and never creates or deletes `gap` rows, only annotates the
`impact_score` column other jobs already wrote. Same footing as
`scope_fetch.py`/`topic_refresh.py`, neither of which has a `detector`
row either.

It computes one score per **(topic, language)** pair -- not per topic --
specifically so it stays genuinely "within a language" rather than being
one global number duplicated everywhere. Three signals, each
`log1p`-transformed then min-max normalized across the current batch,
averaged with equal weight into a single 0-100 number:

- **reach** -- total Wikidata sitelink count for the topic across every
  wiki, not just tracked ones (topic-global; free, reuses the same
  `sitelinks` data several detectors already fetch)
- **catchup** -- how many `gap` rows currently exist for the topic across
  every tracked language and gap type (topic-global; free, pure SQL over
  Duga's own tables)
- **traffic** -- that language's own Wikipedia article's pageviews over
  the last completed month, via the new `get_monthly_pageviews()` helper
  in `jobs/wikimedia_api.py`; 0 if no article exists yet in this language
  (language-specific -- the signal that actually varies per language)

**The score is never displayed anywhere.** It's used only to reorder each
language's own gap list (`app/blueprints/main/routes.py:gaps()`, `ORDER
BY impact_score DESC` with `impact_score IS NULL` sorted first via the
boolean-ordering trick -- portable NULLS-last across SQLite/MariaDB --
falling back to the original recency order for anything unscored). A
visible "score: 87" printed next to a real person's name was considered
and deliberately rejected: even though the number is about article reach,
not the person, a bare number next to a name reads uncomfortably close to
ranking someone's importance (guardrail 12: when in doubt, show less).

**Failure handling is split by signal, deliberately.** Sitelink count and
the internal gap count are both required for a meaningful score, so a
failure fetching sitelinks aborts the *entire* run without committing
anything -- SPEC.md guardrail 9, same as every detector's "fail loudly,
never serve stale data as current without saying so." Pageviews is
different: it's one extra API call per (topic, language) pair with no
batch endpoint, so a single flaky lookup failing the whole day's scoring
for every topic would be a bad trade. A pageviews failure degrades just
that one pair's traffic component to 0 and the run continues; the
closing log line reports how many pairs fell back this way, so a
systemic pageviews outage is still visible in the job's own output even
though it doesn't block the run.

**The pageviews cache (`pageview_cache`).** The traffic signal describes
the most recently *completed* calendar month, so its value cannot change
until the month rolls over -- but the job runs nightly and originally
refetched everything every night. `pageview_cache` keys a count by
`(topic_qid, language_code, month)`, so each pair is fetched once per
month and every later run that month is a single indexed read.

Worth being precise about the size of this problem, because the obvious
estimate is badly wrong. A (topic, language) pair only costs a request if
that language *has* an article -- a pair with no sitelink is the
`no_article` gap itself and is scored 0 without any lookup. Measured on
2026-08-29 with two content languages: 19,221 pairs, of which **1,562**
needed a request. So the cost scales with article coverage, not with the
gap count, and adding a large Wikipedia (en, de, ru) costs far more per
language than adding a small one. The cache still earns its place -- it
takes the recurring nightly cost to near zero -- but the first run of each
month is the only expensive one, and it is minutes, not hours.

Four details worth keeping straight:

- **Failures are never cached.** A 5xx degrades that pair's traffic to 0
  for the run (as before) but writes nothing, or one bad night would pin
  the pair at zero until the month turned over. A genuine 404 is a
  different thing -- `get_monthly_pageviews()` returns 0 rather than
  raising, because "no data for this article" is a real answer -- and
  that 0 *is* cached.
- **A cached value only applies while the article still exists.** Traffic
  means "this language's article's pageviews, 0 if there's no article
  yet", so a topic whose sitelink disappeared since last month scores 0,
  not last month's number.
- **Cache rows commit separately from the scores**, as they are gathered.
  They are facts about a finished month rather than results of a run, so
  a run that dies halfway still leaves the requests it paid for behind for
  the next attempt.
- **Keyed by qid, not by article title.** A page can be renamed between
  runs; the topic is what the score is about, and a completed month's
  count is close enough either way.

Whatever the cache doesn't cover is fetched through a small
`ThreadPoolExecutor` (`PAGEVIEW_WORKERS`, default 8, override with
`DUGA_PAGEVIEW_WORKERS`). Kept modest deliberately: this is a shared, free
API and Duga is one tool among many on Toolforge. The worker threads touch
only `requests` -- never the DB session, which is closed before the loop
for the reason described above.

## Seeding vocabulary in bulk

`scripts/seed_concepts.py` loads concepts and terms from a reviewed JSON
file. The **mechanism is in the repo; the list deliberately is not**.
SPEC.md section 16 leaves the seed concept list open precisely because it
must be "chosen with input from the Wikidata WikiProject LGBT community,
not unilaterally", so shipping fifty concepts of our own choosing would
pre-empt the conversation the spec asks for.
`data/seed_concepts.example.json` documents the format and nothing more.

Two refusals are structural rather than stylistic:

- **No `qid`/`lexeme_id`/`sense_id` fields.** Everything loads as
  `lifecycle = 'local'`. Linking upstream belongs to M7's promotion path,
  which verifies live that the target already exists (SPEC.md section 10);
  a seed file must not become a second, weaker way to claim a Wikidata
  entity.
- **No evidence or evidence_grade.** SPEC.md section 8 computes the grade
  from citations people add, so a seeded term starts at `single_report`
  exactly like one typed into the add-a-term form and earns its grade the
  same way.

The whole file is validated before a single row is written, so a typo in
the last entry can't leave the first half loaded, and `--dry-run` reports
what would happen without writing. Re-running is a no-op (guardrail 8):
concepts match on `local_label` case-insensitively -- the same lookup the
add-a-term route uses -- and terms on (concept, language, written form).

Not applied here: SPEC.md S7's `is_living` exclusion. That constraint is
specifically about experimental detectors and bulk/batch editing
surfaces; impact scoring is a read-only, purely informational sort key
built from data that's already public on the Wikidata item itself
(sitelink count) or already computed elsewhere in Duga (gap count,
pageviews on an article that already exists) -- it doesn't add or infer
anything about a person. This is a judgment call, not an oversight; flag
it if it should be revisited.

## A scope note worth re-checking later

`jobs/wp_no_article.py` reads SPEC.md S7 ("is_living topics excluded from
experimental detectors... and any bulk/batch surface") as applying to batch
*editing* (out of scope for v0.1 per section 9), not a read-only stable-
maturity gap list -- since the topic's in-scope status already passed the
S2 sourced-reference bar, listing "no article yet" adds no new information
about the person. Flag this interpretation if it should be revisited.

## What's deliberately not here yet

All seven milestones in SPEC.md section 14's table (M0-M7) are in place.
Every item in SPEC.md section 11/14's "S1+" row is now built: all six
post-v0.1 *detectors* (Wiktionary, Wikiquote, Wikisource, Commons image,
Commons category, plus the two local-vocabulary detectors -- see the
sections above), each shipping disabled-by-default and scoped to
concepts/topics that already carry a qid (see "Scope decision, not an
oversight" above for what that excludes); lexeme write-back, scoped to
adding a Sense to an existing Lexeme; and impact scoring, designed
together with the tool's operator per SPEC.md section 16's explicit
instruction to satisfy S6 rather than build ahead of that conversation.
Handover terms with the Wikimedia LGBT+ User Group
(SPEC.md section 16) are outside this repo's scope entirely. Suppression now has a self-service UI (see "Self-service suppression"
above); lifting a suppression is still operator-only, on purpose.
