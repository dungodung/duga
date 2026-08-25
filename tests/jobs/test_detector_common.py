from app.extensions import db
from app.models import Detector
from jobs.detector_common import upsert_detector_row


def test_upsert_detector_row_defaults_experimental_to_disabled(app):
    with app.app_context():
        upsert_detector_row("d_exp", "wiktionary", "no_entry", "experimental", "desc", "ok")
        db.session.commit()
        detector = Detector.query.filter_by(detector_key="d_exp").first()
        assert detector.enabled is False


def test_upsert_detector_row_defaults_stable_to_enabled(app):
    with app.app_context():
        upsert_detector_row("d_stable", "wikipedia", "no_article", "stable", "desc", "ok")
        db.session.commit()
        detector = Detector.query.filter_by(detector_key="d_stable").first()
        assert detector.enabled is True


def test_upsert_detector_row_does_not_reset_enabled_on_existing_row(app):
    """Once an operator promotes an experimental detector to enabled, a
    later job run (which only touches last_run_at/last_status on an
    existing row) must not silently flip it back off."""
    with app.app_context():
        upsert_detector_row("d_exp2", "wiktionary", "no_entry", "experimental", "desc", "ok")
        db.session.commit()
        detector = Detector.query.filter_by(detector_key="d_exp2").first()
        detector.enabled = True
        db.session.commit()

        upsert_detector_row("d_exp2", "wiktionary", "no_entry", "experimental", "desc", "ok")
        db.session.commit()
        detector = Detector.query.filter_by(detector_key="d_exp2").first()
        assert detector.enabled is True
