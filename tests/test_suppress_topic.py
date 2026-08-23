from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import Topic
from scripts import suppress_topic


def make_topic(qid="Q1"):
    now = datetime.now(timezone.utc)
    topic = Topic(qid=qid, entity_class="human", is_human=True, is_living=True, first_seen=now, last_seen=now)
    db.session.add(topic)
    db.session.commit()
    return topic


def test_suppress_sets_all_fields(app):
    with app.app_context():
        make_topic()
        suppress_topic.suppress("Q1", "outing risk", "dungodung")

        topic = db.session.get(Topic, "Q1")
        assert topic.suppressed is True
        assert topic.suppressed_reason == "outing risk"
        assert topic.suppressed_by == "dungodung"
        assert topic.suppressed_at is not None


def test_unsuppress_clears_all_fields(app):
    with app.app_context():
        make_topic()
        suppress_topic.suppress("Q1", "test", "dungodung")
        suppress_topic.unsuppress("Q1", "dungodung")

        topic = db.session.get(Topic, "Q1")
        assert topic.suppressed is False
        assert topic.suppressed_reason is None
        assert topic.suppressed_by is None
        assert topic.suppressed_at is None


def test_suppress_unknown_qid_exits_nonzero(app):
    with app.app_context():
        with pytest.raises(SystemExit) as exc_info:
            suppress_topic.suppress("Q404", "reason", "dungodung")
        assert exc_info.value.code != 0


def test_main_requires_reason_when_suppressing(app, capsys):
    with app.app_context():
        make_topic()
    import sys

    argv = sys.argv
    sys.argv = ["suppress_topic.py", "Q1", "--by", "dungodung"]
    try:
        with pytest.raises(SystemExit):
            suppress_topic.main()
    finally:
        sys.argv = argv
