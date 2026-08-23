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
toolforge env set SECRET_KEY "..."       # any random string; only used for Flask's session signing

toolforge build start https://github.com/<your-username>/duga --ref main
toolforge build show   # wait for "ok (Succeeded)"
toolforge webservice buildservice start --mount=none
```

Redeploy after a code change: push `main`, then re-run `toolforge build
start` + `toolforge webservice buildservice restart`.

## Verify

- `https://duga.toolforge.org/` loads the language picker.
- `https://duga.toolforge.org/sr/` and `https://duga.toolforge.org/fr/` load
  translated overview stubs; `https://duga.toolforge.org/xx/` 404s.
- `https://duga.toolforge.org/health` returns `{"status": "ok"}`.
- `https://duga.toolforge.org/about` loads.

## What changes at M1+

- M1 adds ToolsDB (provisioning: `become duga && sql duga`) and the
  `scope_fetch`/`topic_refresh` jobs (`toolforge jobs schedule ...`). DB
  credentials should prefer Toolforge's auto-provisioned `TOOL_TOOLSDB_USER`/
  `TOOL_TOOLSDB_PASSWORD` envvars over anything manually copied, so they stay
  in sync with whatever Toolforge itself rotates.
- M4 adds the Wikimedia OAuth consumer (see the note in SPEC.md section 9)
  and its client id/secret/redirect URI as `toolforge env set` values.
