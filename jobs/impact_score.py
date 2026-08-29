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
import concurrent.futures
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.exc import IntegrityError  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Gap, PageviewCache, Topic  # noqa: E402
from jobs.detector_common import chunks  # noqa: E402
from jobs.wikimedia_api import (  # noqa: E402
    MAX_ENTITY_IDS_PER_REQUEST,
    WikimediaApiError,
    get_entities_batch,
    get_monthly_pageviews,
    previous_month_key,
)
from jobs.wp_no_article import wikipedia_dbname  # noqa: E402

JOB_KEY = "impact_score"

# The pageviews API has no batch endpoint, so the traffic signal costs one
# HTTP request per (topic, language) pair that has an article. Two things
# keep that affordable: `pageview_cache` (a completed month's count never
# changes, so each pair is fetched once per month rather than once per
# night) and a small thread pool for whatever is left. Modest on purpose --
# this is a shared, free API and Duga is one tool among many on Toolforge.
PAGEVIEW_WORKERS = int(os.environ.get("DUGA_PAGEVIEW_WORKERS", "8"))
PAGEVIEW_CACHE_WRITE_CHUNK = 500


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


def _load_cached_pageviews(month):
    """{(topic_qid, language_code): views} already known for `month`."""
    rows = db.session.query(
        PageviewCache.topic_qid, PageviewCache.language_code, PageviewCache.views
    ).filter(PageviewCache.month == month).all()
    return {(qid, lang): views for qid, lang, views in rows}


def _store_pageviews(month, fetched):
    """Persists newly fetched counts. Called repeatedly *during* the fetch
    loop (see _fetch_pageviews' on_batch) and committed as it goes,
    separately from the scores, because these are facts about a finished
    month rather than results of this run -- a run that dies partway
    shouldn't throw away the requests it already paid for.

    Guardrail 8 (assume concurrent re-runs): a parallel run may have
    inserted the same pair between our read and our write, so a chunk that
    collides is retried row by row, skipping what is already there."""
    now = datetime.now(timezone.utc)
    for chunk in chunks(list(fetched.items()), PAGEVIEW_CACHE_WRITE_CHUNK):  # noqa: E501 -- a caller may still hand over more than one chunk's worth
        rows = [
            PageviewCache(topic_qid=qid, language_code=lang, month=month, views=views, fetched_at=now)
            for (qid, lang), views in chunk
        ]
        db.session.add_all(rows)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            for (qid, lang), views in chunk:
                if db.session.get(PageviewCache, (qid, lang, month)) is not None:
                    continue
                db.session.add(
                    PageviewCache(topic_qid=qid, language_code=lang, month=month, views=views, fetched_at=now)
                )
            db.session.commit()


def _fetch_pageviews(app, to_fetch, on_batch=None):
    """Fetches the pairs missing from the cache, PAGEVIEW_WORKERS at a
    time. Returns ({pair: views}, fallback_count).

    Only successful lookups come back in the dict, so only they get
    cached: a pair whose lookup errored falls back to 0 for this run but
    must not have that 0 written to the cache, or one bad night would
    pin it there for the rest of the month. A genuine 404 is not an
    error -- get_monthly_pageviews() returns 0 for it, and that 0 is a
    real answer worth caching.

    `on_batch` is called from *this* thread every
    PAGEVIEW_CACHE_WRITE_CHUNK results with what has accumulated since the
    last call, so a long run persists as it goes instead of holding
    everything until the end -- the first run of a month can be hours of
    requests, and dying at hour two should not throw hour one away. Worker
    threads themselves never touch the DB; they only call `requests`.
    """
    user_agent = app.config["DUGA_USER_AGENT"]
    fetched = {}
    pending = {}
    fallback_count = 0

    def lookup(item):
        (qid, language_code), title = item
        return (qid, language_code), get_monthly_pageviews(language_code, title, user_agent)

    with concurrent.futures.ThreadPoolExecutor(max_workers=PAGEVIEW_WORKERS) as pool:
        futures = {pool.submit(lookup, item): item[0] for item in to_fetch.items()}
        for future in concurrent.futures.as_completed(futures):
            pair = futures[future]
            try:
                key, views = future.result()
            except WikimediaApiError as exc:
                print(
                    f"{JOB_KEY}: pageviews lookup failed for {pair[0]}/{pair[1]}, using 0: {exc}",
                    file=sys.stderr,
                )
                fallback_count += 1
                continue
            fetched[key] = views
            pending[key] = views
            if on_batch is not None and len(pending) >= PAGEVIEW_CACHE_WRITE_CHUNK:
                on_batch(pending)
                pending = {}

    if on_batch is not None and pending:
        on_batch(pending)

    return fetched, fallback_count


def compute_scores(app):
    """Returns ({(topic_qid, language_code): score}, fallback_count) for
    every (topic, language) pair currently represented in `gap`.
    fallback_count is how many pairs had their traffic component zeroed
    out after a pageviews failure. Raises WikimediaApiError if fetching
    sitelinks itself fails -- that's fatal, not something to degrade
    past."""
    pairs = [
        (qid, language_code)
        for qid, language_code in db.session.query(Gap.topic_qid, Gap.language_code)
        .join(Topic, Topic.qid == Gap.topic_qid)
        .filter(Topic.suppressed.is_(False))
        .distinct()
        .all()
    ]
    if not pairs:
        return {}, 0

    qids = sorted({qid for qid, _lang in pairs})

    catchup_by_qid = dict(
        db.session.query(Gap.topic_qid, db.func.count(Gap.id))
        .filter(Gap.topic_qid.in_(qids))
        .group_by(Gap.topic_qid)
        .all()
    )

    # Read the pageview cache while the connection is still open -- every
    # DB read has to happen before the close() below, for the same reason
    # the catchup counts above do.
    month = previous_month_key()
    cached = _load_cached_pageviews(month)

    # Release the DB connection before the slow API loops below -- see
    # jobs/detector_common.py's run_presence_detector for the identical
    # fix and why: holding a connection checked out across a multi-minute
    # API loop (here, potentially thousands of individual pageviews
    # calls) produced "MySQL server has gone away" against ToolsDB in
    # production. SQLAlchemy checks a fresh connection back out lazily
    # the next time db.session is used, e.g. for the writes in run().
    db.session.close()

    sitelinks_by_qid = {}
    for chunk in chunks(qids, MAX_ENTITY_IDS_PER_REQUEST):
        entities = get_entities_batch(app.config["DUGA_WIKIDATA_API"], chunk, "en", app.config["DUGA_USER_AGENT"])
        for qid, info in entities.items():
            sitelinks_by_qid[qid] = info["sitelinks"]

    reach_by_qid = {qid: len(sitelinks_by_qid.get(qid, {})) for qid in qids}

    # A pair with no article in this language has no traffic to look up --
    # that is the `no_article` gap itself, and it costs no request.
    titles_by_pair = {}
    traffic_by_pair = {}
    for qid, language_code in pairs:
        sitelink = sitelinks_by_qid.get(qid, {}).get(wikipedia_dbname(language_code))
        if sitelink is None:
            traffic_by_pair[(qid, language_code)] = 0
        else:
            titles_by_pair[(qid, language_code)] = sitelink["title"]

    # Cached values apply only to pairs that still have an article today.
    # A topic whose sitelink disappeared since last month scores 0 traffic
    # (that is what the traffic signal means), not last month's number.
    traffic_by_pair.update({pair: cached[pair] for pair in titles_by_pair if pair in cached})
    to_fetch = {pair: title for pair, title in titles_by_pair.items() if pair not in cached}

    fetched, fallback_count = _fetch_pageviews(
        app, to_fetch, on_batch=lambda batch: _store_pageviews(month, batch)
    )
    traffic_by_pair.update(fetched)
    # Anything still missing errored out; 0 for this run, uncached.
    for pair in to_fetch:
        traffic_by_pair.setdefault(pair, 0)

    print(
        f"{JOB_KEY}: pageviews for {month} -- "
        f"{len(titles_by_pair) - len(to_fetch)} from cache, "
        f"{len(fetched)} fetched, {fallback_count} failed"
    )

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
