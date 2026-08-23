import json
from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import Detector, Gap, Language, ScopeVersion, Topic
from jobs import wd_no_description

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


def entity(label_lang=None, label_en=None, description_lang=None):
    labels = {}
    if label_lang is not None:
        labels["sr"] = {"value": label_lang, "language": "sr"}
    if label_en is not None:
        labels["en"] = {"value": label_en, "language": "en"}
    descriptions = {}
    if description_lang is not None:
        descriptions["sr"] = {"value": description_lang, "language": "sr"}
    return {"labels": labels, "descriptions": descriptions}


@responses.activate
def test_run_creates_gaps_only_for_topics_missing_a_genuine_description(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1", "Q2")
        seed_languages("sr")

        responses.add(
            responses.GET,
            API_URL,
            json=entities_response(
                {
                    "Q1": entity(label_lang="Има ознаку", description_lang=None),
                    "Q2": entity(label_lang="Друга", description_lang="Има опис"),
                }
            ),
            status=200,
        )
        wd_no_description.run(app)

        gaps = Gap.query.filter_by(language_code="sr", detector_key="wd_no_description").all()
        assert {g.topic_qid for g in gaps} == {"Q1"}
        assert gaps[0].action_url == "https://www.wikidata.org/wiki/Q1#descriptions"
        assert gaps[0].project_code == "wikidata"
        assert gaps[0].gap_type == "no_description"


@responses.activate
def test_run_prefers_own_language_label_over_english_for_display(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1")
        seed_languages("sr")

        responses.add(
            responses.GET,
            API_URL,
            json=entities_response(
                {"Q1": entity(label_lang="Српска ознака", label_en="English label", description_lang=None)}
            ),
            status=200,
        )
        wd_no_description.run(app)

        gap = Gap.query.filter_by(language_code="sr", detector_key="wd_no_description").first()
        assert json.loads(gap.evidence_json)["label"] == "Српска ознака"


@responses.activate
def test_run_falls_back_to_english_label_when_own_language_label_also_missing(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1")
        seed_languages("sr")

        responses.add(
            responses.GET,
            API_URL,
            json=entities_response({"Q1": entity(label_lang=None, label_en="English only", description_lang=None)}),
            status=200,
        )
        wd_no_description.run(app)

        gap = Gap.query.filter_by(language_code="sr", detector_key="wd_no_description").first()
        assert '"label": "English only"' in gap.evidence_json
