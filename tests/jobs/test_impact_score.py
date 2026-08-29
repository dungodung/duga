import re
from datetime import datetime, timezone

import pytest
import responses

from app.extensions import db
from app.models import Gap, Topic
from jobs import impact_score, wikimedia_api

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


# -- pageview caching --------------------------------------------------------
#
# The traffic signal describes a completed calendar month, so it can be
# fetched once per month instead of once per nightly run. These cover that
# the cache is used, filled, and -- the part that matters -- never poisoned
# by a failed lookup.


def _cached_rows():
    from app.models import PageviewCache

    return {(row.topic_qid, row.language_code, row.month): row.views for row in PageviewCache.query.all()}


@responses.activate
def test_run_caches_fetched_pageviews(app):
    with app.app_context():
        seed_topic("Q1")
        make_gap("Q1", "sr", gap_type="no_label", project_code="wikidata")
        mock_sitelinks({"Q1": entity(["srwiki"])})
        mock_pageviews(views=4321)

        impact_score.run(app)

        month = wikimedia_api.previous_month_key()
        assert _cached_rows() == {("Q1", "sr", month): 4321}


@responses.activate
def test_a_second_run_reuses_the_cache_instead_of_refetching(app):
    with app.app_context():
        seed_topic("Q1")
        make_gap("Q1", "sr", gap_type="no_label", project_code="wikidata")
        mock_sitelinks({"Q1": entity(["srwiki"])})
        mock_pageviews(views=4321)
        impact_score.run(app)

        before = len([c for c in responses.calls if "pageviews" in c.request.url])

        responses.reset()
        mock_sitelinks({"Q1": entity(["srwiki"])})
        # No pageviews mock registered at all: a refetch would raise a
        # ConnectionError rather than quietly returning something.
        impact_score.run(app)

        after = len([c for c in responses.calls if "pageviews" in c.request.url])
        assert before == 1
        assert after == 0


@responses.activate
def test_a_failed_lookup_is_not_cached(app):
    """A 5xx degrades this run's traffic to 0 (as before), but writing that
    0 to the cache would pin the pair at zero for the rest of the month."""
    with app.app_context():
        seed_topic("Q1")
        make_gap("Q1", "sr", gap_type="no_label", project_code="wikidata")
        mock_sitelinks({"Q1": entity(["srwiki"])})
        responses.add(responses.GET, PAGEVIEWS_RE, json={"error": "boom"}, status=503)

        impact_score.run(app)

        assert _cached_rows() == {}
        assert Gap.query.filter_by(topic_qid="Q1").one().impact_score is not None


@responses.activate
def test_a_genuine_404_caches_zero(app):
    """404 means "no data for this article", which is a real answer worth
    caching -- get_monthly_pageviews returns 0 rather than raising."""
    with app.app_context():
        seed_topic("Q1")
        make_gap("Q1", "sr", gap_type="no_label", project_code="wikidata")
        mock_sitelinks({"Q1": entity(["srwiki"])})
        responses.add(responses.GET, PAGEVIEWS_RE, json={}, status=404)

        impact_score.run(app)

        month = wikimedia_api.previous_month_key()
        assert _cached_rows() == {("Q1", "sr", month): 0}


@responses.activate
def test_a_cached_value_is_ignored_once_the_article_is_gone(app):
    """Traffic means "this language's article's pageviews, 0 if there is no
    article yet" -- so a sitelink that disappeared scores 0, not last
    month's number."""
    from app.models import PageviewCache

    with app.app_context():
        seed_topic("Q1")
        seed_topic("Q2")
        make_gap("Q1", "sr", gap_type="no_label", project_code="wikidata")
        make_gap("Q2", "sr", gap_type="no_label", project_code="wikidata")
        db.session.add(
            PageviewCache(
                topic_qid="Q1", language_code="sr", month=wikimedia_api.previous_month_key(),
                views=999999, fetched_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()

        # Q1 has no srwiki sitelink any more; Q2 does.
        mock_sitelinks({"Q1": entity([]), "Q2": entity(["srwiki"])})
        mock_pageviews(views=10)
        impact_score.run(app)

        q1 = Gap.query.filter_by(topic_qid="Q1").one().impact_score
        q2 = Gap.query.filter_by(topic_qid="Q2").one().impact_score
        # Q1's stale 999999 was not applied, so it does not outrank Q2.
        assert q1 <= q2


@responses.activate
def test_cache_is_scoped_to_the_month(app):
    from app.models import PageviewCache

    with app.app_context():
        seed_topic("Q1")
        make_gap("Q1", "sr", gap_type="no_label", project_code="wikidata")
        db.session.add(
            PageviewCache(
                topic_qid="Q1", language_code="sr", month="1999-01",
                views=5, fetched_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()

        mock_sitelinks({"Q1": entity(["srwiki"])})
        mock_pageviews(views=77)
        impact_score.run(app)

        # Last month's row was ignored and this month's was fetched.
        month = wikimedia_api.previous_month_key()
        assert _cached_rows()[("Q1", "sr", month)] == 77


@responses.activate
def test_multiple_pairs_are_fetched_through_the_thread_pool(app):
    """Exercises the pool with more pairs than one, since that is the path
    production actually takes."""
    with app.app_context():
        for i in range(1, 6):
            seed_topic(f"Q{i}")
            make_gap(f"Q{i}", "sr", gap_type="no_label", project_code="wikidata")
        mock_sitelinks({f"Q{i}": entity(["srwiki"]) for i in range(1, 6)})
        mock_pageviews(views=100)

        impact_score.run(app)

        month = wikimedia_api.previous_month_key()
        assert _cached_rows() == {(f"Q{i}", "sr", month): 100 for i in range(1, 6)}
        assert Gap.query.filter(Gap.impact_score.is_(None)).count() == 0
