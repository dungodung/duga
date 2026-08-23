import json

import pytest
import responses

from app.extensions import db
from app.models import AuditLog, Contributor


@pytest.fixture()
def oauth_app(app):
    app.config["DUGA_OAUTH_CLIENT_ID"] = "test-client-id"
    app.config["DUGA_OAUTH_CLIENT_SECRET"] = "test-client-secret"
    app.config["DUGA_OAUTH_REDIRECT_URI"] = "http://localhost/oauth/callback"
    return app


def mock_token_and_profile(username="SomeWikiUser", sub=12345):
    responses.add(
        responses.POST,
        "https://meta.wikimedia.org/w/rest.php/oauth2/access_token",
        json={"access_token": "fake-token", "token_type": "Bearer"},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://meta.wikimedia.org/w/rest.php/oauth2/resource/profile",
        json={"sub": sub, "username": username},
        status=200,
    )


def do_login_flow(client):
    """Starts /login, extracts state from the session, then hits the
    callback with a matching state -- the round-trip a browser would do."""
    resp = client.get("/login")
    assert resp.status_code == 302
    assert resp.location.startswith("https://meta.wikimedia.org/w/rest.php/oauth2/authorize")

    with client.session_transaction() as sess:
        state = sess["oauth_state"]

    return client.get(f"/oauth/callback?code=fake-code&state={state}")


# -- /login -----------------------------------------------------------------


def test_login_redirects_to_wikimedia_authorize(client, oauth_app):
    resp = client.get("/login")
    assert resp.status_code == 302
    assert "meta.wikimedia.org/w/rest.php/oauth2/authorize" in resp.location
    assert "client_id=test-client-id" in resp.location


def test_login_shows_not_configured_page_without_credentials(client):
    resp = client.get("/login")
    assert resp.status_code == 503
    assert b"isn&#39;t set up yet" in resp.data or b"Login isn't set up yet" in resp.data


# -- /oauth/callback ----------------------------------------------------------


@responses.activate
def test_callback_creates_a_new_contributor(client, oauth_app, db):
    mock_token_and_profile(username="NewPerson")
    resp = do_login_flow(client)

    assert resp.status_code == 302
    contributor = Contributor.query.filter_by(wiki_username="NewPerson").first()
    assert contributor is not None
    assert contributor.display_public is True
    assert contributor.last_seen_at is not None


@responses.activate
def test_callback_reuses_an_existing_contributor(client, oauth_app, db):
    from datetime import datetime, timezone

    db.session.add(
        Contributor(wiki_username="ReturningPerson", display_public=False, created_at=datetime.now(timezone.utc))
    )
    db.session.commit()

    mock_token_and_profile(username="ReturningPerson")
    do_login_flow(client)

    assert Contributor.query.filter_by(wiki_username="ReturningPerson").count() == 1
    contributor = Contributor.query.filter_by(wiki_username="ReturningPerson").first()
    assert contributor.display_public is False  # untouched by a routine login


@responses.activate
def test_callback_redirects_new_contributor_to_account_page(client, oauth_app):
    mock_token_and_profile(username="NewPerson")
    resp = do_login_flow(client)
    assert resp.headers["Location"].endswith("/account?next=/")


@responses.activate
def test_callback_redirects_returning_contributor_to_next(client, oauth_app, db):
    from datetime import datetime, timezone

    db.session.add(Contributor(wiki_username="ReturningPerson", created_at=datetime.now(timezone.utc)))
    db.session.commit()

    mock_token_and_profile(username="ReturningPerson")
    client.get("/login?next=/sr/gaps")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    resp = client.get(f"/oauth/callback?code=fake-code&state={state}")
    assert resp.headers["Location"] == "/sr/gaps"


def test_callback_rejects_mismatched_state(client, oauth_app):
    client.get("/login")
    resp = client.get("/oauth/callback?code=fake-code&state=wrong-state")
    assert resp.status_code == 400


def test_callback_rejects_missing_code(client, oauth_app):
    client.get("/login")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    resp = client.get(f"/oauth/callback?state={state}")
    assert resp.status_code == 400


@responses.activate
def test_callback_writes_an_audit_log_entry_for_a_new_contributor(client, oauth_app, db):
    mock_token_and_profile(username="AuditedPerson")
    do_login_flow(client)

    entry = AuditLog.query.filter_by(action="create_contributor").first()
    assert entry is not None
    assert entry.actor == "AuditedPerson"
    assert entry.entity_type == "contributor"
    assert json.loads(entry.after_json)["wiki_username"] == "AuditedPerson"


@responses.activate
def test_callback_does_not_audit_log_a_routine_returning_login(client, oauth_app, db):
    from datetime import datetime, timezone

    db.session.add(Contributor(wiki_username="ReturningPerson", created_at=datetime.now(timezone.utc)))
    db.session.commit()

    mock_token_and_profile(username="ReturningPerson")
    do_login_flow(client)

    assert AuditLog.query.count() == 0


# -- /logout ------------------------------------------------------------------


@responses.activate
def test_logout_clears_the_session(client, oauth_app):
    mock_token_and_profile(username="SomePerson")
    do_login_flow(client)

    resp = client.post("/logout")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "contributor_id" not in sess


# -- /account -------------------------------------------------------------


def test_account_redirects_anonymous_visitor_to_login(client):
    resp = client.get("/account")
    assert resp.status_code == 302
    assert "/login" in resp.location


@responses.activate
def test_account_shows_username_when_logged_in(client, oauth_app):
    mock_token_and_profile(username="VisiblePerson")
    do_login_flow(client)

    resp = client.get("/account")
    assert resp.status_code == 200
    assert b"VisiblePerson" in resp.data


@responses.activate
def test_update_attribution_toggles_display_public_and_audit_logs_it(client, oauth_app, db):
    mock_token_and_profile(username="TogglePerson")
    do_login_flow(client)

    resp = client.post("/account/attribution", data={})  # unchecked checkbox
    assert resp.status_code == 302

    contributor = Contributor.query.filter_by(wiki_username="TogglePerson").first()
    assert contributor.display_public is False

    entry = AuditLog.query.filter_by(action="update_attribution").first()
    assert entry is not None
    assert json.loads(entry.before_json)["display_public"] is True
    assert json.loads(entry.after_json)["display_public"] is False


@responses.activate
def test_update_attribution_does_not_audit_log_when_unchanged(client, oauth_app, db):
    mock_token_and_profile(username="StablePerson")
    do_login_flow(client)

    client.post("/account/attribution", data={"display_public": "on"})  # still True, no-op

    assert AuditLog.query.filter_by(action="update_attribution").count() == 0


def test_update_attribution_requires_login(client):
    resp = client.post("/account/attribution", data={})
    assert resp.status_code == 302
    assert "/login" in resp.location
