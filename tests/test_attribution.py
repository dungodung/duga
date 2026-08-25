from datetime import datetime, timezone

from app.attribution import public_name
from app.extensions import db
from app.models import Contributor


def test_public_name_shown_for_opted_in_contributor(app):
    with app.app_context():
        db.session.add(
            Contributor(wiki_username="OptedIn", display_public=True, created_at=datetime.now(timezone.utc))
        )
        db.session.commit()
        assert public_name("OptedIn") == "OptedIn"


def test_public_name_hidden_for_opted_out_contributor(app):
    with app.app_context():
        db.session.add(
            Contributor(wiki_username="OptedOut", display_public=False, created_at=datetime.now(timezone.utc))
        )
        db.session.commit()
        assert public_name("OptedOut") is None


def test_public_name_hidden_when_no_contributor_row_exists(app):
    with app.app_context():
        assert public_name("NeverLoggedIn") is None
