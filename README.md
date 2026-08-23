# Duga

*Rainbow — across the Slavic languages; "to sound the depths" in Indonesian.*

Duga is a multilingual hub that shows what queer knowledge is missing from
Wikimedia projects in your language, and gives you the words and the tools to
add it.

See `SPEC.md` for the full project specification (purpose, hard safety
constraints, data model, milestones). `docs/architecture.md`, `docs/i18n.md`,
`docs/wikiproject-page.md`, `docs/scope-definition.md`, and
`docs/deployment-toolforge.md` cover the current code.

**Status:** M1 — M0's skeleton plus a database (`scope_version`, `scope_rule`,
`topic`, `topic_rule`) and the `scope_fetch`/`topic_refresh` jobs. Still no
OAuth, no detectors, no gap list yet; see the milestone table in `SPEC.md`
section 14. The on-wiki scope definition page (SPEC.md section 6) needs to
exist before these jobs have anything real to do — see
`docs/scope-definition.md`.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make dev-db      # starts a local MariaDB via docker compose
make migrate
make dev
```

Then open http://localhost:5000/ — try the language picker, `/sr/`, `/fr/`,
`/about`, and `/health`.

```bash
make test            # pytest
make run              # gunicorn, the same entrypoint Toolforge uses (Procfile)
make scope-fetch      # jobs/scope_fetch.py against DUGA_SCOPE_PAGE
make topic-refresh    # jobs/topic_refresh.py against the active scope_version
```

## Deployment

See `docs/deployment-toolforge.md` for the GitHub → Toolforge Build Service
runbook.

## Licence

AGPL-3.0 (see `LICENSE`). Data is CC0 where it mirrors Wikidata, CC BY-SA for
prose contributions — see `SPEC.md`.
