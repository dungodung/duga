from datetime import datetime, timezone

import pytest
import responses

from app.extensions import db
from app.models import Detector, Gap, Language, ScopeVersion, Topic
from jobs import wp_no_article

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


def entity(sitelinks=None, label=None, language="sr"):
    body = {"sitelinks": {site: {"site": site, "title": "x", "badges": []} for site in (sitelinks or [])}}
    if label is not None:
        body["labels"] = {language: {"value": label, "language": language}}
    else:
        body["labels"] = {}
    return body


def test_wikipedia_dbname_default_and_override():
    assert wp_no_article.wikipedia_dbname("sr") == "srwiki"
    assert wp_no_article.wikipedia_dbname("nb") == "nowiki"


def test_run_creates_gaps_only_for_topics_missing_the_article(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1", "Q2")
        seed_languages("sr")

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                API_URL,
                json=entities_response(
                    {
                        "Q1": entity(sitelinks=["enwiki"], label="Has no sr article"),
                        "Q2": entity(sitelinks=["srwiki", "enwiki"], label="Has sr article"),
                    }
                ),
                status=200,
            )
            wp_no_article.run(app)

        gaps = Gap.query.filter_by(language_code="sr").all()
        assert {g.topic_qid for g in gaps} == {"Q1"}
        assert '"label": "Has no sr article"' in gaps[0].evidence_json
        assert gaps[0].action_url == "https://www.wikidata.org/wiki/Q1#sitelinks-wikipedia"

        detector = Detector.query.filter_by(detector_key="wp_no_article").first()
        assert detector.last_status == "ok"
        assert detector.maturity == "stable"


def test_run_is_idempotent_and_drops_topics_that_gained_an_article(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1")
        seed_languages("sr")

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET, API_URL,
                json=entities_response({"Q1": entity(sitelinks=[], label="Missing")}),
                status=200,
            )
            wp_no_article.run(app)
        assert Gap.query.filter_by(language_code="sr").count() == 1

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET, API_URL,
                json=entities_response({"Q1": entity(sitelinks=["srwiki"], label="Missing")}),
                status=200,
            )
            wp_no_article.run(app)
        assert Gap.query.filter_by(language_code="sr").count() == 0


def test_run_exits_loudly_with_no_active_scope_version(app):
    with app.app_context():
        seed_languages("sr")
        with pytest.raises(SystemExit):
            wp_no_article.run(app)


def test_run_exits_loudly_with_no_seeded_languages(app):
    with app.app_context():
        seed_active_scope_version()
        with pytest.raises(SystemExit):
            wp_no_article.run(app)


def test_run_leaves_existing_gaps_untouched_on_api_failure(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topics("Q1")
        seed_languages("sr")

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET, API_URL,
                json=entities_response({"Q1": entity(sitelinks=[], label="Missing")}),
                status=200,
            )
            wp_no_article.run(app)
        assert Gap.query.count() == 1

        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, API_URL, json={"error": "boom"}, status=500)
            with pytest.raises(SystemExit):
                wp_no_article.run(app)

        assert Gap.query.count() == 1
        detector = Detector.query.filter_by(detector_key="wp_no_article").first()
        assert detector.last_status == "error"


def test_run_chunks_requests_over_fifty_topics(app):
    with app.app_context():
        seed_active_scope_version()
        qids = [f"Q{i}" for i in range(60)]
        seed_topics(*qids)
        seed_languages("sr")

        first_chunk = {qid: entity(sitelinks=[], label=qid) for qid in qids[:50]}
        second_chunk = {qid: entity(sitelinks=[], label=qid) for qid in qids[50:]}

        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, API_URL, json=entities_response(first_chunk), status=200)
            rsps.add(responses.GET, API_URL, json=entities_response(second_chunk), status=200)
            wp_no_article.run(app)

        assert Gap.query.filter_by(language_code="sr").count() == 60
