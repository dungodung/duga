"""Toolforge job: impact scoring (SPEC.md section 11/16, "S1+"). Computes
a per-(topic, language) score used *only* to order each language's own
gap list (SPEC.md S6: "Impact scoring ranks topics within a language. It
never ranks languages against each other") -- the raw number is never
shown anywhere; see docs/architecture.md's "Impact scoring" section for
the full design rationale. Not a detector: it doesn't own a gap_type or
create/delete gap rows, only annotates gap.impact_score on rows other
jobs already wrote -- same footing as scope_fetch.py/topic_refresh.py,
neither of which has a `detector` row either.

Combines three signals into one 0-100 score per (topic_qid,
language_code) pair, each log1p-transformed then min-max normalized
across the current batch before being averaged with equal weight:

  - reach:    total Wikidata sitelink count for the topic, across every
              wiki, not just tracked ones (topic-global)
  - catchup:  how many gap rows currently exist for the topic across
              every tracked language and gap type (topic-global)
  - traffic:  that language's own Wikipedia article's pageviews over the
              last completed month, 0 if no article exists yet in this
              language (language-specific -- the one signal that keeps
              this genuinely "within a language" rather than duplicating
              one global number everywhere)

reach and catchup come from data Duga already has cheaply. A pageviews
API failure for one topic degrades that topic's traffic component to 0
and the run continues (the closing log line reports how many topics fell
back this way); a failure fetching sitelinks, or a database error,
aborts the whole run without committing anything, leaving the previous
run's scores in place (SPEC.md guardrail 9: fail loudly, never serve a
half-written result as complete).

Run via: python3 jobs/impact_score.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Gap, Topic  # noqa: E402
from jobs.detector_common import chunks  # noqa: E402
from jobs.wikimedia_api import (  # noqa: E402
    MAX_ENTITY_IDS_PER_REQUEST,
    WikimediaApiError,
    get_entities_batch,
    get_monthly_pageviews,
)
from jobs.wp_no_article import wikipedia_dbname  # noqa: E402

JOB_KEY = "impact_score"


def _normalize(raw_values: dict) -> dict:
    """log1p each value, then min-max normalize into [0, 1]. Falls back
    to 0.0 for every entry when everything ties (max == min), rather
    than dividing by zero."""
    transformed = {key: math.log1p(max(value, 0)) for key, value in raw_values.items()}
    if not transformed:
        return {}
    lo, hi = min(transformed.values()), max(transformed.values())
    if hi == lo:
        return {key: 0.0 for key in transformed}
    return {key: (value - lo) / (hi - lo) for key, value in transformed.items()}


def compute_scores(app):
    """Returns ({(topic_qid, language_code): score}, fallback_count) for
    every (topic, language) pair currently represented in `gap`.
    fallback_count is how many pairs had their traffic component zeroed
    out after a pageviews failure. Raises WikimediaApiError if fetching
    sitelinks itself fails -- that's fatal, not something to degrade
    past."""
    pairs = (
        db.session.query(Gap.topic_qid, Gap.language_code)
        .join(Topic, Topic.qid == Gap.topic_qid)
        .filter(Topic.suppressed.is_(False))
        .distinct()
        .all()
    )
    if not pairs:
        return {}, 0

    qids = sorted({qid for qid, _lang in pairs})

    sitelinks_by_qid = {}
    for chunk in chunks(qids, MAX_ENTITY_IDS_PER_REQUEST):
        entities = get_entities_batch(app.config["DUGA_WIKIDATA_API"], chunk, "en", app.config["DUGA_USER_AGENT"])
        for qid, info in entities.items():
            sitelinks_by_qid[qid] = info["sitelinks"]

    reach_by_qid = {qid: len(sitelinks_by_qid.get(qid, {})) for qid in qids}

    catchup_by_qid = dict(
        db.session.query(Gap.topic_qid, db.func.count(Gap.id))
        .filter(Gap.topic_qid.in_(qids))
        .group_by(Gap.topic_qid)
        .all()
    )

    traffic_by_pair = {}
    fallback_count = 0
    for qid, language_code in pairs:
        dbname = wikipedia_dbname(language_code)
        sitelink = sitelinks_by_qid.get(qid, {}).get(dbname)
        if sitelink is None:
            traffic_by_pair[(qid, language_code)] = 0
            continue
        try:
            traffic_by_pair[(qid, language_code)] = get_monthly_pageviews(
                language_code, sitelink["title"], app.config["DUGA_USER_AGENT"]
            )
        except WikimediaApiError as exc:
            print(f"{JOB_KEY}: pageviews lookup failed for {qid}/{language_code}, using 0: {exc}", file=sys.stderr)
            traffic_by_pair[(qid, language_code)] = 0
            fallback_count += 1

    reach_norm = _normalize(reach_by_qid)
    catchup_norm = _normalize(catchup_by_qid)
    traffic_norm = _normalize(traffic_by_pair)

    scores = {}
    for qid, language_code in pairs:
        parts = [reach_norm.get(qid, 0.0), catchup_norm.get(qid, 0.0), traffic_norm.get((qid, language_code), 0.0)]
        scores[(qid, language_code)] = round(100 * (sum(parts) / len(parts)), 4)

    return scores, fallback_count


def run(app=None):
    app = app or create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        try:
            scores, fallback_count = compute_scores(app)
        except WikimediaApiError as exc:
            print(f"{JOB_KEY} FAILED: {exc}", file=sys.stderr)
            sys.exit(1)

        if not scores:
            print(f"{JOB_KEY}: no gap rows to score -- nothing to do")
            return

        for (qid, language_code), score in scores.items():
            Gap.query.filter_by(topic_qid=qid, language_code=language_code).update(
                {"impact_score": score}, synchronize_session=False
            )
        db.session.commit()

        print(
            f"{JOB_KEY}: scored {len(scores)} (topic, language) pairs "
            f"({fallback_count} with a pageviews fallback to 0)"
        )


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- a job must fail loudly, never swallow errors
        print(f"{JOB_KEY} FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
