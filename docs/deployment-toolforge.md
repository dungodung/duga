# GitHub → Toolforge deployment runbook

Duga deploys to Wikimedia Toolforge via **Build Service** (the Kubernetes-backed
buildpack pipeline — `toolforge build` / `toolforge webservice buildservice`),
the same mechanism WikiWhiz uses. The one simplification here: Duga has no
frontend build step (server-rendered Jinja, vanilla JS, no bundler — see
SPEC.md section 5), so unlike WikiWhiz there is no separate `deploy` branch
with prebuilt assets baked in. Build Service can build directly from `main`
on GitHub; a plain `pip install` is the only build Duga ever needs.

## One-time setup

1. **Create the Toolforge tool** (from `login.toolforge.org`, requires an
   approved Toolforge account):
   ```
   toolforge tools create duga
   toolforge tools maintainers add duga <your-username>
   ```
2. Confirm `duga.toolforge.org` and check Toolhub for name collisions (see
   SPEC.md section 17) — do this before relying on the URL anywhere public.
3. ToolsDB provisioning and OAuth consumer registration are **not needed for
   M0** — the app has no database and no login yet. Both land with M1/M4
   respectively; see `docs/i18n.md` for what M0 actually ships.

## Deploying / redeploying

Toolforge Build Service accepts any reachable git URL, including a public
GitHub repo — it does not require GitLab:

```
become duga
toolforge envvars create SECRET_KEY "$(openssl rand -hex 32)"   # avoid printing the value; the command echoes it back

toolforge build start https://github.com/<your-username>/duga --ref main
toolforge build show   # wait for "Status: ok"
toolforge webservice buildservice start --mount=none
```

(Verified against the actual CLI: it's `toolforge envvars create NAME VALUE`,
not `toolforge env set` -- some older docs/muscle memory say otherwise.)

Redeploy after a code change: push `main`, then re-run `toolforge build
start` + `toolforge webservice buildservice restart`.

## Verify

- `https://duga.toolforge.org/` loads the language picker.
- `https://duga.toolforge.org/sr/` and `https://duga.toolforge.org/fr/` load
  translated overview stubs; `https://duga.toolforge.org/xx/` 404s.
- `https://duga.toolforge.org/health` returns `{"status": "ok"}`.
- `https://duga.toolforge.org/about` loads.

## M1: database and jobs

ToolsDB is auto-provisioned per-tool the moment the tool exists -- no manual
`sql duga` step needed. `TOOL_TOOLSDB_USER`/`TOOL_TOOLSDB_PASSWORD` are
injected automatically into `toolforge jobs run` containers and into the
buildservice webservice pod (confirmed live); `app/config.py` prefers them
over `DB_USER`/`DB_PASSWORD` so nothing needs to be copied by hand. They are
**not** exported into an interactive `become duga` bastion shell, only into
job/webservice pods -- run anything that needs the DB as a job, not
directly on the bastion.

Apply migrations after each build that changes the schema, as a one-off job
against the tool's own freshly-built image:

```
toolforge build start https://github.com/<your-username>/duga --ref main
toolforge build show   # wait for "Status: ok"
toolforge jobs run migrate --command "flask --app wsgi db upgrade" \
  --image tool-duga/tool-duga:latest --wait
toolforge jobs logs migrate   # confirm it applied cleanly, then:
toolforge jobs delete migrate
```

Fetch the on-wiki scope definition (see `docs/scope-definition.md` for what
needs to exist on Wikidata first) and populate topics:

```
toolforge jobs run scope-fetch --command "python3 jobs/scope_fetch.py" \
  --image tool-duga/tool-duga:latest --wait
toolforge jobs run activate-scope --command "python3 scripts/activate_scope_version.py --list" \
  --image tool-duga/tool-duga:latest --wait
toolforge jobs logs activate-scope   # note the id to activate, then:
toolforge jobs run activate-scope --command "python3 scripts/activate_scope_version.py <id> --by <your-wiki-username>" \
  --image tool-duga/tool-duga:latest --wait
toolforge jobs run topic-refresh --command "python3 jobs/topic_refresh.py" \
  --image tool-duga/tool-duga:latest --wait
toolforge jobs delete scope-fetch
toolforge jobs delete activate-scope
toolforge jobs delete topic-refresh
```

(`jobs delete` takes exactly one job name per call, not a list.)

Once that's worked once by hand, schedule the two recurring jobs (`--wait`
replaced with `--schedule`; a cron-like expression, evaluated in UTC):

```
toolforge jobs run scope-fetch --command "python3 jobs/scope_fetch.py" \
  --image tool-duga/tool-duga:latest --schedule "0 3 * * *" --emails onfailure
toolforge jobs run topic-refresh --command "python3 jobs/topic_refresh.py" \
  --image tool-duga/tool-duga:latest --schedule "30 3 * * *" --emails onfailure
```

`topic_refresh` only acts on the *active* scope_version (SPEC.md section 6),
so scheduling it doesn't risk silently adopting an unreviewed scope change --
activation stays a deliberate, separate step
(`scripts/activate_scope_version.py`) until M4 adds an admin UI for it.

## M2 + M3: detectors, overrides, suppression

The three v0.1 detectors run the same way as `topic_refresh` above -- each
can spend several minutes making hundreds of Wikimedia API calls, so run
them one at a time the first time and watch `toolforge jobs logs`:

```
toolforge jobs run wp-no-article --command "python3 jobs/wp_no_article.py" \
  --image tool-duga/tool-duga:latest --wait 900
toolforge jobs run wd-no-label --command "python3 jobs/wd_no_label.py" \
  --image tool-duga/tool-duga:latest --wait 900
toolforge jobs run wd-no-description --command "python3 jobs/wd_no_description.py" \
  --image tool-duga/tool-duga:latest --wait 900
```

(`--wait` defaults to a 600s client-side timeout; pass a larger value like
`--wait 900` for these rather than the bare flag, or the CLI gives up
watching before a slow run finishes -- the job itself still completes
server-side either way.)

Then schedule all three, staggered so they don't compete for API rate
budget, and after `topic_refresh` has had time to finish first:

```
toolforge jobs run wp-no-article --command "python3 jobs/wp_no_article.py" \
  --image tool-duga/tool-duga:latest --schedule "0 4 * * *" --emails onfailure
toolforge jobs run wd-no-label --command "python3 jobs/wd_no_label.py" \
  --image tool-duga/tool-duga:latest --schedule "20 4 * * *" --emails onfailure
toolforge jobs run wd-no-description --command "python3 jobs/wd_no_description.py" \
  --image tool-duga/tool-duga:latest --schedule "40 4 * * *" --emails onfailure
```

Suppressing a topic or overriding a specific gap (SPEC.md S4, guardrail 5)
is a one-off job the same way scope activation is -- there's no admin UI
until M4:

```
toolforge jobs run suppress --command "python3 scripts/suppress_topic.py Q42 --reason '...' --by <your-wiki-username>" \
  --image tool-duga/tool-duga:latest --wait
toolforge jobs run override --command "python3 scripts/set_gap_override.py Q42 sr wikipedia no_article --status done --by <your-wiki-username>" \
  --image tool-duga/tool-duga:latest --wait
toolforge jobs delete suppress
toolforge jobs delete override
```

## M4 (later)

Adds the Wikimedia OAuth consumer (see the note in SPEC.md section 9) and
its client id/secret/redirect URI as `toolforge envvars create` values.
