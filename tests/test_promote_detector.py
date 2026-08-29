"""scripts/promote_detector.py -- the human decision SPEC.md section 11
reserves, with the S7 consequence made explicit at the point of decision."""
import pytest

from app.extensions import db
from app.models import AuditLog, Detector, Topic
from scripts import promote_detector


def make_detector(maturity="experimental", enabled=True):
    detector = Detector(
        detector_key="commons_no_image", project_code="commons", gap_type="no_image",
        maturity=maturity, enabled=enabled,
    )
    db.session.add(detector)
    db.session.commit()
    return detector


def make_living_topic(qid, is_living=True, suppressed=False):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(qid=qid, entity_class="human", is_human=True, is_living=is_living,
              first_seen=now, last_seen=now, suppressed=suppressed)
    )
    db.session.commit()


def test_promotion_needs_two_reviewers(app):
    with app.app_context():
        detector = make_detector()
        with pytest.raises(SystemExit) as exc:
            promote_detector.promote(detector, "beta", ["Only One (sr)"], "dungodung", True)
        assert exc.value.code == 1
        assert Detector.query.one().maturity == "experimental"


def test_promotion_needs_explicit_confirmation(app):
    with app.app_context():
        detector = make_detector()
        with pytest.raises(SystemExit) as exc:
            promote_detector.promote(detector, "beta", ["A (sr)", "B (fr)"], "dungodung", False)
        assert exc.value.code == 1
        assert Detector.query.one().maturity == "experimental"


def test_promotion_records_reviewers_and_the_s7_change(app):
    with app.app_context():
        detector = make_detector()
        promote_detector.promote(detector, "beta", ["A (sr)", "B (fr)"], "dungodung", True)

        assert Detector.query.one().maturity == "beta"
        entry = AuditLog.query.filter_by(action="promote_detector").one()
        assert "A (sr)" in entry.after_json
        assert '"s7_exclusion_lifted": true' in entry.after_json


def test_promotion_leaves_enabled_alone(app):
    with app.app_context():
        detector = make_detector(enabled=False)
        promote_detector.promote(detector, "stable", ["A (sr)", "B (fr)"], "dungodung", True)

        row = Detector.query.one()
        assert row.maturity == "stable"
        assert row.enabled is False


def test_demotion_needs_no_reviewers_or_confirmation(app):
    """Making living-person handling stricter again never needs ceremony."""
    with app.app_context():
        detector = make_detector(maturity="stable")
        promote_detector.promote(detector, "experimental", [], "dungodung", False)

        assert Detector.query.one().maturity == "experimental"
        assert AuditLog.query.filter_by(action="set_detector_maturity").count() == 1


def test_a_sideways_promotion_between_non_experimental_levels_is_not_gated(app):
    with app.app_context():
        detector = make_detector(maturity="beta")
        promote_detector.promote(detector, "stable", [], "dungodung", False)
        assert Detector.query.one().maturity == "stable"


def test_living_topic_count_ignores_suppressed_and_non_living(app):
    with app.app_context():
        make_living_topic("Q1")
        make_living_topic("Q2", suppressed=True)
        make_living_topic("Q3", is_living=False)
        assert promote_detector.living_topic_count() == 1
