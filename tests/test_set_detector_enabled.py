"""scripts/set_detector_enabled.py -- the operator switch that makes a
detector's gaps visible without promoting its maturity (SPEC.md section 11
keeps those two decisions separate; see S7 for why the difference matters)."""
from app.extensions import db
from app.models import AuditLog, Detector
from scripts import set_detector_enabled


def make_detector(key="commons_no_image", maturity="experimental", enabled=False):
    detector = Detector(
        detector_key=key, project_code="commons", gap_type="no_image",
        maturity=maturity, enabled=enabled,
    )
    db.session.add(detector)
    db.session.commit()
    return detector


def test_enabling_leaves_maturity_untouched(app):
    """The whole point of the script: enabling makes gaps visible, but
    maturity stays experimental, so jobs/detector_common.py keeps excluding
    living people (SPEC.md S7) and every row still reads 'experimental'."""
    with app.app_context():
        detector = make_detector()
        set_detector_enabled.set_enabled([detector], True, "dungodung")

        row = Detector.query.filter_by(detector_key="commons_no_image").one()
        assert row.enabled is True
        assert row.maturity == "experimental"


def test_enabling_is_audit_logged_with_both_fields(app):
    with app.app_context():
        detector = make_detector()
        set_detector_enabled.set_enabled([detector], True, "dungodung")

        entry = AuditLog.query.filter_by(action="enable_detector").one()
        assert entry.actor == "dungodung"
        assert entry.entity_id == "commons_no_image"
        assert '"enabled": false' in entry.before_json
        assert '"enabled": true' in entry.after_json
        # Records the maturity it did *not* change, so the log shows a
        # reader that this was not a promotion.
        assert '"maturity": "experimental"' in entry.after_json


def test_disabling_reverses_it(app):
    with app.app_context():
        detector = make_detector(enabled=True)
        set_detector_enabled.set_enabled([detector], False, "dungodung")

        assert Detector.query.filter_by(detector_key="commons_no_image").one().enabled is False
        assert AuditLog.query.filter_by(action="disable_detector").count() == 1


def test_a_no_op_change_is_not_logged(app):
    with app.app_context():
        detector = make_detector(enabled=True)
        set_detector_enabled.set_enabled([detector], True, "dungodung")

        assert AuditLog.query.count() == 0


def test_exits_when_no_detector_matches(app):
    with app.app_context():
        try:
            set_detector_enabled.set_enabled([], True, "dungodung")
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")
