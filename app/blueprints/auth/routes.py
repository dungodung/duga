from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from ...audit import log as audit_log
from ...extensions import db
from ...models import Contributor
from . import oauth_client

auth_bp = Blueprint("auth", __name__)


def current_contributor():
    contributor_id = session.get("contributor_id")
    if not contributor_id:
        return None
    return db.session.get(Contributor, contributor_id)


def login_required(view):
    """Every write route in SPEC.md section 12's route table is marked
    "(auth required)" -- this is the one place that requirement is enforced,
    so every such route just needs this decorator rather than repeating the
    same redirect-to-login check.

    The forms that POST to these routes only render when already logged in,
    so a logged-out visitor hitting one at all is an edge case (a stale
    session, a resubmitted form), not the primary path -- ?next= is only
    meaningful for GET pages; for a POST it would send a logged-in-again
    visitor back to a POST-only URL via GET and 405. Home is a fine
    fallback for that edge case.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_contributor() is None:
            target = request.path if request.method == "GET" else url_for("main.home")
            return redirect(url_for("auth.login", next=target))
        return view(*args, **kwargs)

    return wrapped


def _safe_next(target):
    """Only ever redirect to a same-site relative path -- an open redirect
    via ?next= would let a phishing link ride Duga's own login flow."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.home")


@auth_bp.get("/login")
def login():
    client_id = current_app.config["DUGA_OAUTH_CLIENT_ID"]
    if not client_id:
        return render_template("oauth_not_configured.html"), 503

    state = oauth_client.new_state()
    session["oauth_state"] = state
    session["oauth_next"] = _safe_next(request.args.get("next"))
    url = oauth_client.build_authorize_url(client_id, current_app.config["DUGA_OAUTH_REDIRECT_URI"], state)
    return redirect(url)


@auth_bp.get("/oauth/callback")
def callback():
    expected_state = session.pop("oauth_state", None)
    next_url = session.pop("oauth_next", None) or url_for("main.home")
    state = request.args.get("state")
    code = request.args.get("code")
    if not code or not state or state != expected_state:
        return render_template("oauth_error.html"), 400

    token = oauth_client.exchange_code_for_token(
        current_app.config["DUGA_OAUTH_CLIENT_ID"],
        current_app.config["DUGA_OAUTH_CLIENT_SECRET"],
        current_app.config["DUGA_OAUTH_REDIRECT_URI"],
        code,
    )
    profile = oauth_client.fetch_profile(token["access_token"])
    username = profile["username"]

    now = datetime.now(timezone.utc)
    contributor = Contributor.query.filter_by(wiki_username=username).first()
    is_new = contributor is None
    if is_new:
        contributor = Contributor(wiki_username=username, display_public=True, created_at=now)
        db.session.add(contributor)
        db.session.flush()  # assigns contributor.id, used below
        # A login itself is routine telemetry, not an auditable decision --
        # but a *new* contributor row being created is worth a record
        # (guardrail 11), same bar as the attribution preference below.
        audit_log(
            actor=username,
            action="create_contributor",
            entity_type="contributor",
            entity_id=contributor.id,
            before=None,
            after={"wiki_username": username, "display_public": True},
        )
    contributor.last_seen_at = now
    db.session.commit()

    session["contributor_id"] = contributor.id
    session.permanent = True

    if is_new:
        return redirect(url_for("auth.account", next=next_url))
    return redirect(next_url)


@auth_bp.post("/logout")
def logout():
    session.pop("contributor_id", None)
    return redirect(url_for("main.home"))


@auth_bp.get("/account")
@login_required
def account():
    contributor = current_contributor()
    continue_url = _safe_next(request.args.get("next"))
    return render_template("account.html", contributor=contributor, continue_url=continue_url)


@auth_bp.post("/account/attribution")
@login_required
def update_attribution():
    contributor = current_contributor()

    before = contributor.display_public
    contributor.display_public = request.form.get("display_public") == "on"
    if before != contributor.display_public:
        audit_log(
            actor=contributor.wiki_username,
            action="update_attribution",
            entity_type="contributor",
            entity_id=contributor.id,
            before={"display_public": before},
            after={"display_public": contributor.display_public},
        )
    db.session.commit()
    return redirect(url_for("auth.account"))
