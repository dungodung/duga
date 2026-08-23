# Duga

*Rainbow — across the Slavic languages; "to sound the depths" in Indonesian.*

Duga is a multilingual hub that shows what queer knowledge is missing from
Wikimedia projects in your language, and gives you the words and the tools to
add it.

See `SPEC.md` for the full project specification (purpose, hard safety
constraints, data model, milestones). `docs/architecture.md`, `docs/i18n.md`,
`docs/wikiproject-page.md`, `docs/scope-definition.md`, and
`docs/deployment-toolforge.md` cover the current code.

**Status:** M2 — the first end-to-end slice (SPEC.md section 14). A visitor
can pick a language, see real gaps (`wp_no_article`: missing Wikipedia
articles), and click through to fix one on Wikidata. Still no OAuth, no
overrides/suppression UI (M3), no writes to Wikidata (M6).

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
make test              # pytest
make run                # gunicorn, the same entrypoint Toolforge uses (Procfile)
make scope-fetch        # jobs/scope_fetch.py against DUGA_SCOPE_PAGE
make topic-refresh      # jobs/topic_refresh.py against the active scope_version
make wp-no-article      # jobs/wp_no_article.py -- the wp_no_article detector
```

## Deployment

See `docs/deployment-toolforge.md` for the GitHub → Toolforge Build Service
runbook.

## Licence

AGPL-3.0 (see `LICENSE`). Data is CC0 where it mirrors Wikidata, CC BY-SA for
prose contributions — see `SPEC.md`.
