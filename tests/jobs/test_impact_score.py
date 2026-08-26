import re
from datetime import datetime, timezone

import pytest
import responses

from app.extensions import db
from app.models import Gap, Topic
from jobs import impact_score

API_URL = "https://www.wikidata.org/w/api.php"
PAGEVIEWS_RE = re.compile(r"https://wikimedia\.org/api/rest_v1/metrics/pageviews/per-article/.+/monthly/\d+/\d+")


def seed_topic(qid, suppressed=False):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(qid=qid, entity_class="human", is_human=True, is_living=False, first_seen=now, last_seen=now, suppressed=suppressed)
    )
    db.session.commit()


def make_gap(qid, lang, gap_type="no_article", project_code="wikipedia"):
    now = datetime.now(timezone.utc)
    gap = Gap(
        topic_qid=qid,
        language_code=lang,
        project_code=project_code,
        gap_type=gap_type,
        detector_key=f"wd_{gap_type}",
        scope_version_id=1,
        evidence_json="{}",
        action_url="https://example.org",
        computed_at=now,
    )
    db.session.add(gap)
    db.session.commit()
    return gap


def entities_response(entities):
    return {"entities": entities}


def entity(sitelinks=None):
    return {"sitelinks": {site: {"site": site, "title": "Some Title"} for site in (sitelinks or [])}, "labels": {}}


def mock_sitelinks(entities):
    responses.add(responses.GET, API_URL, json=entities_response(entities), status=200)


def mock_pageviews(views=0):
    responses.add(responses.GET, PAGEVIEWS_RE, json={"items": [{"views": views}]}, status=200)


@responses.activate
def test_run_scores_higher_reach_topic_higher(app):
    with app.app_context():
        seed_topic("Q1")  # many sitelinks -> higher reach
        seed_topic("Q2")  # few sitelinks -> lower reach
        make_gap("Q1", "sr")
        make_gap("Q2", "sr")

        mock_sitelinks(
            {
                "Q1": entity(sitelinks=[f"lang{i}wiki" for i in range(50)] + ["srwiki"]),
                "Q2": entity(sitelinks=["srwiki"]),
            }
        )
        mock_pageviews(views=0)
        mock_pageviews(views=0)

        impact_score.run(app)

        q1 = Gap.query.filter_by(topic_qid="Q1", language_code="sr").first()
        q2 = Gap.query.filter_by(topic_qid="Q2", language_code="sr").first()
        assert q1.impact_score > q2.impact_score


@responses.activate
def test_run_applies_same_score_to_every_gap_row_for_the_pair(app):
    with app.app_context():
        seed_topic("Q1")
        make_gap("Q1", "sr", gap_type="no_article", project_code="wikipedia")
        make_gap("Q1", "sr", gap_type="no_label", project_code="wikidata")

        mock_sitelinks({"Q1": entity(sitelinks=["srwiki"])})
        mock_pageviews(views=10)

        impact_score.run(app)

        gaps = Gap.query.filter_by(topic_qid="Q1", language_code="sr").all()
        assert len({g.impact_score for g in gaps}) == 1
        assert gaps[0].impact_score is not None


@responses.activate
def test_run_excludes_suppressed_topics(app):
    with app.app_context():
        seed_topic("Q1", suppressed=True)
        make_gap("Q1", "sr")

        impact_score.run(app)  # no API mocks registered -- must not call out at all

        assert Gap.query.filter_by(topic_qid="Q1").first().impact_score is None


def test_run_is_a_no_op_with_no_gap_rows(app):
    with app.app_context():
        impact_score.run(app)  # must not raise, no API calls needed


@responses.activate
def test_run_falls_back_to_zero_traffic_on_pageviews_failure(app):
    with app.app_context():
        seed_topic("Q1")
        make_gap("Q1", "sr")

        mock_sitelinks({"Q1": entity(sitelinks=["srwiki"])})
        responses.add(responses.GET, PAGEVIEWS_RE, status=500, body="boom")

        scores, fallback_count = impact_score.compute_scores(app)
        assert fallback_count == 1
        assert scores[("Q1", "sr")] is not None  # still scored, just with traffic=0


@responses.activate
def test_run_aborts_without_committing_on_sitelinks_failure(app):
    with app.app_context():
        seed_topic("Q1")
        gap = make_gap("Q1", "sr")
        gap.impact_score = 42.0
        db.session.commit()

        responses.add(responses.GET, API_URL, json={"error": "boom"}, status=500)

        with pytest.raises(SystemExit):
            impact_score.run(app)

        # Previous score untouched.
        assert Gap.query.filter_by(topic_qid="Q1").first().impact_score == 42.0
