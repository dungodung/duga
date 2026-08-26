import json
from datetime import datetime, timezone

from app.extensions import db
from app.models import Detector, Gap, ScopeVersion
from jobs.detector_common import replace_gaps, upsert_detector_row


def seed_active_scope_version():
    version = ScopeVersion(
        source_page="Wikidata:WikiProject LGBT/Duga/scope",
        revision_id=1,
        raw_json="{}",
        fetched_at=datetime.now(timezone.utc),
        active=True,
    )
    db.session.add(version)
    db.session.commit()
    return version.id


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


def test_replace_gaps_uses_default_action_url_fn_when_no_override_given(app):
    with app.app_context():
        version_id = seed_active_scope_version()
        replace_gaps(
            "d_default_url", "wikipedia", "no_article",
            {"sr": {"Q1": {"label": "Example"}}},
            version_id,
            action_url_fn=lambda qid, lang: f"https://example.org/{qid}/{lang}",
        )
        db.session.commit()
        gap = Gap.query.filter_by(detector_key="d_default_url").first()
        assert gap.action_url == "https://example.org/Q1/sr"
        assert json.loads(gap.evidence_json) == {"label": "Example"}


def test_replace_gaps_prefers_per_gap_action_url_override(app):
    with app.app_context():
        version_id = seed_active_scope_version()
        replace_gaps(
            "d_override_url", "vocabulary", "no_evidence",
            {"sr": {"Q1": {"label": "Example", "_action_url": "/sr/vocabulary/42#add-evidence-form"}}},
            version_id,
            action_url_fn=lambda qid, lang: "should-not-be-used",
        )
        db.session.commit()
        gap = Gap.query.filter_by(detector_key="d_override_url").first()
        assert gap.action_url == "/sr/vocabulary/42#add-evidence-form"
        # The override key never leaks into stored evidence.
        assert json.loads(gap.evidence_json) == {"label": "Example"}
