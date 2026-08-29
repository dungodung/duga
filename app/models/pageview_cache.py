from ..extensions import db


class PageviewCache(db.Model):
    """One month's pageview count for one (topic, language) pair.

    Impact scoring's traffic signal is "that language's Wikipedia article's
    pageviews over the most recently completed calendar month" -- a value
    that, by definition, cannot change until the month rolls over. The job
    runs nightly, so without this table it refetched every pair every night:
    one sequential HTTP call per pair, no batch endpoint (see
    jobs/wikimedia_api.py:get_monthly_pageviews). At two content languages
    that was tolerable; at eleven it is roughly 275,000 calls a night, which
    does not fit in any sane job window.

    Keyed by qid rather than by article title: the title can be renamed
    between runs, but the topic is what the score is about, and a month's
    completed pageview count is close enough either way. `month` is the
    completed month the number describes ('YYYY-MM'), not when it was
    fetched -- that is `fetched_at`.

    Rows are facts about a finished month, not results of a particular run,
    so impact_score commits them as it goes rather than with the scores at
    the end: a run that later fails still leaves the fetches it paid for
    behind for the next attempt.
    """

    __tablename__ = "pageview_cache"

    topic_qid = db.Column(db.String(16), primary_key=True)
    language_code = db.Column(db.String(20), primary_key=True)
    month = db.Column(db.String(7), primary_key=True)
    views = db.Column(db.Integer, nullable=False)
    fetched_at = db.Column(db.DateTime, nullable=False)

    __table_args__ = (db.Index("ix_pageview_cache_month", "month"),)
