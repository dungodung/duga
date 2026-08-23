from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import Detector, Gap, Language, ScopeVersion, Topic
from jobs import wd_no_label

API_URL = "https://www.wikidata.org/w/api.php"


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
    return version


def seed_topics(*qids):
    now = datetime.now(timezone.utc)
    for qid in qids:
        db.session.add(
            Topic(qid=qid, entity_class="human", is_human=True, is_living=True, first_seen=now, last_seen=now)
        )
    db.session.commit()


def seed_languages(*codes):
    for code in codes:
        db.session.add(Language(code=code, autonym=code, seeded=True))
    db.session.commit()


def entities_response(entities):
    return {"entities": entities}


def entity(label_lang=None, label_en=None):
    labels = {}
    if label_lang is not None:
        labels["sr"] = {"value": label_lang, "language": "sr"}
    if label_en is not None:
        labels["en"] = {"value": label_en, "language": "en"}
    return {"labels": labels, "descriptions": {}}


@responses.activate
def test_run_creates_gaps_only_for_topics_missing_a_genuine_label(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1", "Q2")
        seed_languages("sr")

        responses.add(
            responses.GET,
            API_URL,
            json=entities_response(
                {
                    "Q1": entity(label_lang=None, label_en="Has no sr label"),
                    "Q2": entity(label_lang="Има ознаку", label_en="Has a label"),
                }
            ),
            status=200,
        )
        wd_no_label.run(app)

        gaps = Gap.query.filter_by(language_code="sr", detector_key="wd_no_label").all()
        assert {g.topic_qid for g in gaps} == {"Q1"}
        assert '"label": "Has no sr label"' in gaps[0].evidence_json
        assert gaps[0].action_url == "https://www.wikidata.org/wiki/Q1#labels"
        assert gaps[0].project_code == "wikidata"
        assert gaps[0].gap_type == "no_label"

        detector = Detector.query.filter_by(detector_key="wd_no_label").first()
        assert detector.last_status == "ok"
        assert detector.maturity == "stable"


@responses.activate
def test_run_ignores_fallback_derived_labels(app):
    """A label present only via MediaWiki's own fallback chain (not
    requested here at all, since get_raw_labels_and_descriptions never
    passes languagefallback) must still count as missing."""
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1")
        seed_languages("sr")

        # No "sr" key in labels at all -- exactly what a real "genuinely
        # missing in sr" response looks like without languagefallback.
        responses.add(
            responses.GET,
            API_URL,
            json=entities_response({"Q1": entity(label_lang=None, label_en="English only")}),
            status=200,
        )
        wd_no_label.run(app)

        assert Gap.query.filter_by(language_code="sr", detector_key="wd_no_label").count() == 1
