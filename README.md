# Duga

*Rainbow — across the Slavic languages; "to sound the depths" in Indonesian.*

Duga is a multilingual hub that shows what queer knowledge is missing from
Wikimedia projects in your language, and gives you the words and the tools to
add it.

See `SPEC.md` for the full project specification (purpose, hard safety
constraints, data model, milestones). `docs/architecture.md`, `docs/i18n.md`,
`docs/wikiproject-page.md`, `docs/scope-definition.md`, `docs/oauth-setup.md`,
and `docs/deployment-toolforge.md` cover the current code.

**Status:** all seven milestones (M0-M7) are live. A logged-in visitor can
fix a `no_label`/`no_description` Wikidata gap directly from the gap list:
preview the exact edit, confirm, and it's written to Wikidata under their
own account (never as identity statements — see SPEC.md S1). Writes are
gated by a global kill switch (`DUGA_WRITES_ENABLED`) and per-user/global
hourly rate limits, and every attempt is recorded in `audit_log` and
`wiki_edit` before and after the call. A local concept or term can be
proposed and then linked to an *existing* Wikidata item or Lexeme (SPEC.md
section 10) — this never creates anything on Wikidata, only links to
something a live lookup confirms already exists. Any logged-in visitor can
also mark a gap `declined`/`not_applicable` directly from the gap list
(`POST /gap/override`), and suppress a topic, concept, or term from the
page they're looking at — a confirmation page states the blast radius, a
reason is required, and it's one-way (only an operator lifts a
suppression). An operator can additionally mark a gap `done` via
`scripts/set_gap_override.py`. All six
post-v0.1 detectors from SPEC.md section 11 are also in place — Wiktionary,
Wikiquote, Wikisource sitelink presence; Commons image/category claim
presence; and `vocab_no_term`/`vocab_no_evidence`, which check Duga's own
local vocabulary tables instead of Wikidata — all shipping
`maturity = 'experimental'`. Their gaps are now visible in production:
`scripts/set_detector_enabled.py` flips visibility *without* touching
maturity, so the rows still read "experimental" and SPEC.md S7 keeps
living people out of them. Promotion to `beta`/`stable` is a separate,
still-unmade human decision (SPEC.md section 11: review with native
speakers of at least two affected languages). Lexeme write-back is also live: a term already linked to an
existing Wikidata Lexeme but with no Sense yet can have one added —
gloss, preview, confirm, same kill switch and rate limits as every other
write — via "Add a sense to this Lexeme" on the term's page; this never
creates a new Lexeme, only a Sense on one that already exists. Impact
scoring is also live — a per-(topic, language) score, computed daily from
Wikidata sitelink count, Duga's own gap count, and that language's own
Wikipedia pageviews, used only to reorder each language's gap list
(highest-reach topics first); the score itself is never shown (SPEC.md
S6: it only ever ranks topics within one language, never languages
against each other). See `docs/architecture.md` for the full design and
for the qid-only scoping the two vocabulary detectors use — every item in
SPEC.md's "S1+" milestone row is now built.

**Login needs a registered OAuth consumer to actually work** — see
`docs/oauth-setup.md` for the one manual step (`DUGA_OAUTH_CLIENT_ID`/
`_SECRET`); without it, `/login` shows a plain "not configured" page rather
than breaking.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make dev-db      # starts a local MariaDB via docker compose
make migrate
make dev
```

Then open http://localhost:5000/ — try the language picker, `/sr/`,
`/sr/gaps`, `/sr/vocabulary`, `/about`, `/health`, and (once
`DUGA_OAUTH_CLIENT_ID` is set -- see `docs/oauth-setup.md`) `/login`.

```bash
make test               # pytest
make run                 # gunicorn, the same entrypoint Toolforge uses (Procfile)
make scope-fetch         # jobs/scope_fetch.py against DUGA_SCOPE_PAGE
make topic-refresh       # jobs/topic_refresh.py against the active scope_version
make wp-no-article       # jobs/wp_no_article.py -- missing Wikipedia articles
make wd-no-label         # jobs/wd_no_label.py -- missing Wikidata labels
make wd-no-description   # jobs/wd_no_description.py -- missing Wikidata descriptions
make wiktionary-no-entry     # jobs/wiktionary_no_entry.py -- experimental
make wikiquote-no-quotes     # jobs/wikiquote_no_quotes.py -- experimental
make wikisource-no-text      # jobs/wikisource_no_text.py -- experimental
make commons-no-image        # jobs/commons_no_image.py -- experimental
make commons-no-category     # jobs/commons_no_category.py -- experimental
make vocab-no-term           # jobs/vocab_no_term.py -- experimental
make vocab-no-evidence       # jobs/vocab_no_evidence.py -- experimental
make impact-score            # jobs/impact_score.py -- scores gap.impact_score, run last
```

Duga tracks eleven content languages: the ten largest Wikipedias by
article count (en, ceb, de, fr, sv, nl, es, ru, it, pl) plus sr. The
interface is translated into ten of them — everything but Cebuano, which
nobody here can check; see `docs/i18n.md` for why the seven newest
translations are marked unreviewed. SPEC.md section 13 keeps the two sets
independent, so a missing interface translation never limits which
languages Duga tracks gaps for.

Operator actions (most of the rest is self-service now — see
`docs/architecture.md`):

```bash
# setting a suppression is in the UI; lifting one stays operator-only
python3 scripts/suppress_topic.py <QID> --unsuppress --by <your-wiki-username>
python3 scripts/suppress_vocabulary.py term <id> --unsuppress --by <your-wiki-username>
python3 scripts/set_gap_override.py <QID> <lang> <project> <gap_type> --status done --by <your-wiki-username>
python3 scripts/set_detector_enabled.py --list
python3 scripts/set_detector_enabled.py <detector_key> --off --by <your-wiki-username>

# promotion out of 'experimental' -- needs two named reviewers and --yes,
# because it lifts SPEC.md S7's living-person exclusion for that detector
python3 scripts/promote_detector.py <detector_key> --to beta \
    --reviewer "Name (sr)" --reviewer "Name (fr)" --by <your-wiki-username> --yes

# bulk-load reviewed vocabulary; the concept list itself is a community
# decision and is not in this repo (see data/seed_concepts.example.json)
python3 scripts/seed_concepts.py <file.json> --by <your-wiki-username> --dry-run
```

## Deployment

See `docs/deployment-toolforge.md` for the GitHub → Toolforge Build Service
runbook.

## Licence

AGPL-3.0 (see `LICENSE`). Data is CC0 where it mirrors Wikidata, CC BY-SA for
prose contributions — see `SPEC.md`.
