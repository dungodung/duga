import pytest

from app.extensions import db
from app.models import GapOverride
from scripts import set_gap_override


def test_set_override_creates_a_new_row(app):
    with app.app_context():
        set_gap_override.set_override("Q1", "sr", "wikipedia", "no_article", "done", "dungodung", "fixed it")

        override = GapOverride.query.filter_by(topic_qid="Q1").first()
        assert override.status == "done"
        assert override.reason == "fixed it"
        assert override.set_by == "dungodung"
        assert override.set_at is not None


def test_set_override_updates_an_existing_row_instead_of_duplicating(app):
    with app.app_context():
        set_gap_override.set_override("Q1", "sr", "wikipedia", "no_article", "declined", "dungodung", "first")
        set_gap_override.set_override("Q1", "sr", "wikipedia", "no_article", "done", "dungodung", "second")

        assert GapOverride.query.filter_by(topic_qid="Q1").count() == 1
        override = GapOverride.query.filter_by(topic_qid="Q1").first()
        assert override.status == "done"
        assert override.reason == "second"


def test_clear_override_removes_the_row(app):
    with app.app_context():
        set_gap_override.set_override("Q1", "sr", "wikipedia", "no_article", "done", "dungodung", None)
        set_gap_override.clear_override("Q1", "sr", "wikipedia", "no_article")

        assert GapOverride.query.filter_by(topic_qid="Q1").count() == 0


def test_clear_override_on_nonexistent_row_does_not_raise(app, capsys):
    with app.app_context():
        set_gap_override.clear_override("Q404", "sr", "wikipedia", "no_article")
        captured = capsys.readouterr()
        assert "No override existed" in captured.err


def test_override_is_scoped_to_the_exact_gap_type(app):
    with app.app_context():
        set_gap_override.set_override("Q1", "sr", "wikipedia", "no_article", "done", "dungodung", None)
        set_gap_override.set_override("Q1", "sr", "wikidata", "no_label", "declined", "dungodung", None)

        assert GapOverride.query.filter_by(topic_qid="Q1").count() == 2


def test_main_rejects_invalid_status(app):
    import sys

    argv = sys.argv
    sys.argv = [
        "set_gap_override.py", "Q1", "sr", "wikipedia", "no_article",
        "--status", "bogus", "--by", "dungodung",
    ]
    try:
        with pytest.raises(SystemExit):
            set_gap_override.main()
    finally:
        sys.argv = argv
