# Registering a Wikimedia OAuth 2.0 consumer

Duga logs contributors in via Wikimedia's Central Auth (the same account
used across Wikipedia, Wikidata, Commons, etc.) -- SPEC.md section 9: "No
Duga-local passwords, ever." This step is **manual** and must be done by a
maintainer (it requires your own Wikimedia account) -- Claude Code cannot do
this for you.

## Steps

1. Go to <https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration/propose>
   while logged into your Wikimedia account.
2. Choose **OAuth 2.0**, "This consumer is for use in a web application"
   (not owner-only).
3. Fill in:
   - **Application name**: `Duga` (or `Duga (dev)` for a separate local
     development consumer -- register two, one per callback URL, since a
     consumer maps to exactly one callback).
   - **Description**: a short description, e.g. linking to the project
     overview page (`Wikidata:WikiProject LGBT/Duga`) and/or the GitHub repo.
   - **Callback URL**:
     - dev consumer: `http://localhost:5000/oauth/callback`
     - prod consumer: `https://duga.toolforge.org/oauth/callback`
   - **Applicable project**: "all projects" (so any Wikimedia account works,
     not just en.wikipedia.org accounts).
   - **Grants**: identity only, for now. M4 (this milestone) only logs
     people in -- it never edits anything. **Do not** request any edit
     grants yet; broadening this consumer's permissions is a decision for
     M6, when the labels/descriptions write path actually lands, and even
     then SPEC.md S1 requires it to go through an explicit property
     allowlist. Requesting more than identity now would be asking for
     permissions the code can't use and doesn't need.
4. Submit. Approval for a non-owner-only consumer can take some time
   (reviewed by OAuth admins) -- start this early, it doesn't block any
   other work.
5. Once approved, you'll have a **Client ID** and **Client secret**. Set them:
   - Locally: in `.env`, as `DUGA_OAUTH_CLIENT_ID` / `DUGA_OAUTH_CLIENT_SECRET`
     (and `DUGA_OAUTH_REDIRECT_URI` to match the dev callback above).
   - In production: via `toolforge envvars create` (see
     `deployment-toolforge.md`) -- the client secret will get echoed back to
     your terminal when you set it, same caveat as `SECRET_KEY`.

## How it's used in code

`app/blueprints/auth/oauth_client.py` implements the Authorization Code flow
against `meta.wikimedia.org/w/rest.php/oauth2/*` (endpoint shape verified
against a working production integration, not re-derived from scratch --
see the module docstring): `GET /login` redirects to Wikimedia's authorize
endpoint with a random `state`; `GET /oauth/callback` validates that `state`
(CSRF protection), exchanges the code for an access token, fetches the
profile, and upserts a `Contributor` row keyed by the profile's `username`.
The access/refresh tokens are never persisted past that one request.

A brand-new contributor is sent to `/account` first (not straight to
wherever they were headed) to see the public-attribution opt-out prominently,
per SPEC.md section 9 -- `?next=` carries them onward from there. Every
contributor-affecting write (new contributor, attribution change) gets an
`audit_log` row (guardrail 11); routine returning logins don't, to keep that
table meaningful rather than growing one row per visit.

If `DUGA_OAUTH_CLIENT_ID` is unset, `/login` shows a plain "not configured"
page instead of crashing -- safe to deploy before registration finishes.
