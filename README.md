# Duga

*Rainbow — across the Slavic languages; "to sound the depths" in Indonesian.*

Duga is a multilingual hub that shows what queer knowledge is missing from
Wikimedia projects in your language, and gives you the words and the tools to
add it.

See `SPEC.md` for the full project specification (purpose, hard safety
constraints, data model, milestones). `docs/architecture.md`, `docs/i18n.md`,
`docs/wikiproject-page.md`, `docs/scope-definition.md`, and
`docs/deployment-toolforge.md` cover the current code.

**Status:** M3 — all three v0.1 detectors (`wp_no_article`, `wd_no_label`,
`wd_no_description`), gap overrides, and topic suppression. A visitor can
pick a language, see real gaps, and click through to fix one on Wikidata;
an operator can suppress a topic or override a specific gap via
`scripts/suppress_topic.py`/`scripts/set_gap_override.py` (no self-service
UI for either until M4 brings OAuth). Still no writes to Wikidata (M6).

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
`/sr/gaps`, `/about`, and `/health`.

```bash
make test               # pytest
make run                 # gunicorn, the same entrypoint Toolforge uses (Procfile)
make scope-fetch         # jobs/scope_fetch.py against DUGA_SCOPE_PAGE
make topic-refresh       # jobs/topic_refresh.py against the active scope_version
make wp-no-article       # jobs/wp_no_article.py -- missing Wikipedia articles
make wd-no-label         # jobs/wd_no_label.py -- missing Wikidata labels
make wd-no-description   # jobs/wd_no_description.py -- missing Wikidata descriptions
```

Operator actions (no auth'd UI yet -- see `docs/architecture.md`):

```bash
python3 scripts/suppress_topic.py <QID> --reason "..." --by <your-wiki-username>
python3 scripts/set_gap_override.py <QID> <lang> <project> <gap_type> --status done --by <your-wiki-username>
```

## Deployment

See `docs/deployment-toolforge.md` for the GitHub → Toolforge Build Service
runbook.

## Licence

AGPL-3.0 (see `LICENSE`). Data is CC0 where it mirrors Wikidata, CC BY-SA for
prose contributions — see `SPEC.md`.
