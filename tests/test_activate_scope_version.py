from datetime import datetime, timezone

from app.extensions import db
from app.models import ScopeVersion
from scripts import activate_scope_version as activate_cli


def make_version(revision_id, active=False):
    version = ScopeVersion(
        source_page="Wikidata:WikiProject LGBT/Duga/scope",
        revision_id=revision_id,
        raw_json="{}",
        fetched_at=datetime.now(timezone.utc),
        active=active,
    )
    db.session.add(version)
    db.session.commit()
    return version


def test_activate_sets_active_and_metadata(app):
    with app.app_context():
        version = make_version(1)
        activate_cli.activate(version.id, "SomeWikiUser")
        refreshed = db.session.get(ScopeVersion, version.id)
        assert refreshed.active is True
        assert refreshed.activated_by == "SomeWikiUser"
        assert refreshed.activated_at is not None


def test_activating_a_new_version_deactivates_the_old_one(app):
    with app.app_context():
        old = make_version(1, active=True)
        new = make_version(2)

        activate_cli.activate(new.id, "SomeWikiUser")

        assert db.session.get(ScopeVersion, old.id).active is False
        assert db.session.get(ScopeVersion, new.id).active is True


def test_activate_unknown_id_exits_nonzero(app, capsys):
    with app.app_context():
        try:
            activate_cli.activate(9999, "SomeWikiUser")
            assert False, "expected SystemExit"
        except SystemExit as exc:
            assert exc.code != 0
