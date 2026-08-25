from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import Detector, Gap, Language, ScopeVersion, Topic
from jobs import wiktionary_no_entry

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


def seed_topic(qid, is_living=True):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(qid=qid, entity_class="human", is_human=True, is_living=is_living, first_seen=now, last_seen=now)
    )
    db.session.commit()


def seed_languages(*codes):
    for code in codes:
        db.session.add(Language(code=code, autonym=code, seeded=True))
    db.session.commit()


def entities_response(entities):
    return {"entities": entities}


def entity(sitelinks=None, label=None, language="sr"):
    body = {"sitelinks": {site: {"site": site, "title": "x", "badges": []} for site in (sitelinks or [])}}
    body["labels"] = {language: {"value": label, "language": language}} if label is not None else {}
    return body


@responses.activate
def test_run_creates_gaps_only_for_non_living_topics_missing_the_entry(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_topic("Q2", is_living=True)  # excluded from this experimental detector by S7
        seed_languages("sr")

        responses.add(
            responses.GET,
            API_URL,
            json=entities_response({"Q1": entity(sitelinks=[], label="Has no sr entry")}),
            status=200,
        )
        wiktionary_no_entry.run(app)

        gaps = Gap.query.filter_by(language_code="sr").all()
        assert {g.topic_qid for g in gaps} == {"Q1"}
        assert gaps[0].project_code == "wiktionary"
        assert gaps[0].gap_type == "no_entry"
        assert gaps[0].action_url == "https://www.wikidata.org/wiki/Q1#sitelinks-wiktionary"

        detector = Detector.query.filter_by(detector_key="wiktionary_no_entry").first()
        assert detector.maturity == "experimental"
        assert detector.enabled is False
        assert detector.last_status == "ok"


@responses.activate
def test_run_is_idempotent(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_languages("sr")

        responses.add(
            responses.GET, API_URL,
            json=entities_response({"Q1": entity(sitelinks=[], label="Missing")}),
            status=200,
        )
        wiktionary_no_entry.run(app)
        assert Gap.query.count() == 1

        responses.reset()
        responses.add(
            responses.GET, API_URL,
            json=entities_response({"Q1": entity(sitelinks=["srwiktionary"], label="Missing")}),
            status=200,
        )
        wiktionary_no_entry.run(app)
        assert Gap.query.count() == 0
