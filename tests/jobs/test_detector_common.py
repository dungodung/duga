import json
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import Detector, Gap, ScopeVersion
from jobs.detector_common import replace_gaps, run_presence_detector, upsert_detector_row
from jobs.wikimedia_api import WikimediaApiError


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


# -- per-language chunking and failure handling -------------------------------
#
# All of this comes from a real incident: wp_no_article died ~13 minutes
# into a ten-language sweep on 2026-08-30, threw away every language's
# work, and -- because the exception was a bare requests error rather than
# a WikimediaApiError -- never marked its own detector row, so the UI went
# on showing the previous day's gaps as current.


def _detector_kwargs(compute_fn, maturity="stable"):
    return dict(
        detector_key="test_detector",
        project_code="wikipedia",
        gap_type="no_article",
        maturity=maturity,
        description="test",
        action_url_fn=lambda qid, lang: f"https://example.org/{qid}",
        compute_fn=compute_fn,
    )


def _seed(db, languages=("sr", "fr")):
    from app.models import Language, Topic

    seed_active_scope_version()
    now = datetime.now(timezone.utc)
    for code in languages:
        db.session.add(Language(code=code, autonym=code, seeded=True))
    db.session.add(
        Topic(qid="Q1", entity_class="concept", is_human=False, is_living=False, first_seen=now, last_seen=now)
    )
    db.session.commit()


def test_one_language_failing_does_not_discard_the_others(app):
    with app.app_context():
        _seed(db)

        def compute(app_, language_code, qids):
            if language_code == "fr":
                raise WikimediaApiError("connection reset")
            return {"Q1": {"label": "Kept"}}

        with pytest.raises(SystemExit) as exc:
            run_presence_detector(app, **_detector_kwargs(compute))
        assert exc.value.code == 1

        # The language that worked is written and committed...
        assert Gap.query.filter_by(language_code="sr").count() == 1
        assert Gap.query.filter_by(language_code="fr").count() == 0
        # ...and the run is still loudly a failure.
        assert Detector.query.one().last_status == "error"


def test_a_non_api_exception_still_marks_the_detector_errored(app):
    """The original bug: only WikimediaApiError was caught, so a plain
    requests error escaped and left last_status untouched -- the UI then
    served stale gaps as current, which guardrail 9 forbids."""
    with app.app_context():
        _seed(db, languages=("sr",))

        def compute(app_, language_code, qids):
            raise ConnectionResetError("connection reset by peer")

        with pytest.raises(SystemExit):
            run_presence_detector(app, **_detector_kwargs(compute))

        assert Detector.query.one().last_status == "error"


def test_a_clean_run_is_marked_ok(app):
    with app.app_context():
        _seed(db)
        run_presence_detector(
            app, **_detector_kwargs(lambda app_, lang, qids: {"Q1": {"label": "x"}})
        )
        assert Detector.query.one().last_status == "ok"
        assert Gap.query.count() == 2


def test_languages_flag_restricts_the_run(app, monkeypatch):
    """The manual lever for re-running just the language that failed."""
    with app.app_context():
        _seed(db)
        monkeypatch.setattr("sys.argv", ["wp_no_article.py", "--languages", "fr"])
        run_presence_detector(
            app, **_detector_kwargs(lambda app_, lang, qids: {"Q1": {"label": "x"}})
        )
        assert Gap.query.filter_by(language_code="fr").count() == 1
        assert Gap.query.filter_by(language_code="sr").count() == 0


def test_languages_flag_rejects_an_unseeded_language(app, monkeypatch):
    with app.app_context():
        _seed(db)
        monkeypatch.setattr("sys.argv", ["wp_no_article.py", "--languages", "xx"])
        with pytest.raises(SystemExit) as exc:
            run_presence_detector(
                app, **_detector_kwargs(lambda app_, lang, qids: {})
            )
        assert exc.value.code == 1
