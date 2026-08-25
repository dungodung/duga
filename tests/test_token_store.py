from datetime import datetime, timedelta, timezone

import pytest
import responses

from app.extensions import db
from app.models import Contributor, ContributorToken
from app.token_crypto import decrypt
from app.token_store import TokenUnavailable, get_valid_access_token, save_tokens

TOKEN_URL = "https://meta.wikimedia.org/w/rest.php/oauth2/access_token"


def make_contributor(app):
    contributor = Contributor(wiki_username="Someone", created_at=datetime.now(timezone.utc))
    db.session.add(contributor)
    db.session.commit()
    return contributor


def test_save_tokens_encrypts_at_rest(app):
    with app.app_context():
        contributor = make_contributor(app)
        save_tokens(contributor.id, "access-123", "refresh-456", 3600)
        db.session.commit()

        row = db.session.get(ContributorToken, contributor.id)
        assert row.access_token_encrypted != "access-123"
        assert row.refresh_token_encrypted != "refresh-456"
        key = app.config["DUGA_TOKEN_ENCRYPTION_KEY"]
        assert decrypt(key, row.access_token_encrypted) == "access-123"
        assert decrypt(key, row.refresh_token_encrypted) == "refresh-456"


def test_save_tokens_upserts_rather_than_duplicating(app):
    with app.app_context():
        contributor = make_contributor(app)
        save_tokens(contributor.id, "first-token", "refresh", 3600)
        db.session.commit()
        save_tokens(contributor.id, "second-token", "refresh", 3600)
        db.session.commit()

        assert ContributorToken.query.filter_by(contributor_id=contributor.id).count() == 1
        row = db.session.get(ContributorToken, contributor.id)
        key = app.config["DUGA_TOKEN_ENCRYPTION_KEY"]
        assert decrypt(key, row.access_token_encrypted) == "second-token"


def test_get_valid_access_token_returns_fresh_token_without_refreshing(app):
    with app.app_context():
        contributor = make_contributor(app)
        save_tokens(contributor.id, "fresh-token", "refresh", 3600)
        db.session.commit()

        assert get_valid_access_token(contributor.id) == "fresh-token"


def test_get_valid_access_token_raises_when_nothing_stored(app):
    with app.app_context():
        contributor = make_contributor(app)
        with pytest.raises(TokenUnavailable):
            get_valid_access_token(contributor.id)


@responses.activate
def test_get_valid_access_token_refreshes_an_expired_token(app):
    with app.app_context():
        contributor = make_contributor(app)
        save_tokens(contributor.id, "old-token", "refresh-token", 3600)
        row = db.session.get(ContributorToken, contributor.id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)  # force expiry
        db.session.commit()

        responses.add(
            responses.POST,
            TOKEN_URL,
            json={"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 3600},
            status=200,
        )

        token = get_valid_access_token(contributor.id)
        assert token == "new-token"

        key = app.config["DUGA_TOKEN_ENCRYPTION_KEY"]
        row = db.session.get(ContributorToken, contributor.id)
        assert decrypt(key, row.access_token_encrypted) == "new-token"
        assert decrypt(key, row.refresh_token_encrypted) == "new-refresh"


def test_get_valid_access_token_raises_when_expired_with_no_refresh_token(app):
    with app.app_context():
        contributor = make_contributor(app)
        save_tokens(contributor.id, "old-token", None, 3600)
        row = db.session.get(ContributorToken, contributor.id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.session.commit()

        with pytest.raises(TokenUnavailable):
            get_valid_access_token(contributor.id)


@responses.activate
def test_get_valid_access_token_raises_when_refresh_fails(app):
    with app.app_context():
        contributor = make_contributor(app)
        save_tokens(contributor.id, "old-token", "refresh-token", 3600)
        row = db.session.get(ContributorToken, contributor.id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.session.commit()

        responses.add(responses.POST, TOKEN_URL, json={"error": "invalid_grant"}, status=400)

        with pytest.raises(TokenUnavailable):
            get_valid_access_token(contributor.id)
