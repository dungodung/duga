import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seed_languages(db):
    """Mirrors the seed data the real M2 migration inserts (sr, fr content
    languages + the wikipedia project) -- db.create_all() builds schema
    only, not migration data, so tests that exercise content-language
    routes need this explicitly."""
    from app.models import Language, Project

    db.session.add_all(
        [
            Language(code="sr", autonym="Српски", seeded=True),
            Language(code="fr", autonym="Français", seeded=True),
            Project(code="wikipedia", family="wikipedia"),
        ]
    )
    db.session.commit()
