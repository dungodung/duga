"""Toolforge job: the wp_no_article detector -- missing Wikipedia articles
for in-scope topics, one gap type in the unifying (topic, language, project,
gap_type, evidence, action, status) record shape (SPEC.md section 1, 11).
v0.1 detector, maturity 'stable'.

Run via: python3 jobs/wp_no_article.py
Idempotent (SPEC.md guardrail 8) and fails loudly (guardrail 9) -- see
jobs/detector_common.py's run_presence_detector for the shared mechanics
every "is X missing" detector uses.

Note on SPEC.md S7 ("is_living topics are excluded from experimental
detectors by default and from any bulk/batch surface"): this detector is a
read-only, 'stable'-maturity gap *list* -- it never edits anything and adds
no information beyond "an article doesn't exist yet" for a topic whose
in-scope status already passed the S2 sourced-reference bar. "Bulk/batch
surface" is read here as batch *editing* (SPEC.md section 9, explicitly
out of scope for v0.1), not a read-only list -- flag this interpretation if
it should be revisited.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from jobs.detector_common import chunks, run_presence_detector  # noqa: E402
from jobs.wikimedia_api import MAX_ENTITY_IDS_PER_REQUEST, get_entities_batch  # noqa: E402

DETECTOR_KEY = "wp_no_article"
PROJECT_CODE = "wikipedia"
GAP_TYPE = "no_article"
DESCRIPTION = "Missing Wikipedia article in a tracked language for an in-scope topic."

# Wikipedia site-key exceptions where it isn't simply f"{code}wiki" --
# extend as new seeded languages hit one (SPEC.md section 13: Wikimedia
# language codes, not ISO, and Wikipedia's own db-name convention has its
# own historical quirks on top of that).
WIKIPEDIA_DBNAME_OVERRIDES = {
    "nb": "nowiki",
}


def wikipedia_dbname(language_code: str) -> str:
    return WIKIPEDIA_DBNAME_OVERRIDES.get(language_code, f"{language_code}wiki")


def action_url(qid: str, language_code: str) -> str:
    # This detector's destination is on Wikidata, same URL for every
    # language -- language_code is part of the shared action_url_fn
    # signature (see jobs/detector_common.py) but unused here.
    return f"https://www.wikidata.org/wiki/{qid}#sitelinks-wikipedia"


def compute_gaps_for_language(app, language_code, qids):
    """Returns {qid: {"label": str|None}} for topics with no Wikipedia
    article in `language_code`. Raises WikimediaApiError on any batch
    failure. Takes a plain code, not a Language ORM object -- this runs
    with the DB session closed, so an ORM instance could raise
    DetachedInstanceError the moment something tried to lazily touch it."""
    dbname = wikipedia_dbname(language_code)
    missing = {}
    for chunk in chunks(qids, MAX_ENTITY_IDS_PER_REQUEST):
        entities = get_entities_batch(
            app.config["DUGA_WIKIDATA_API"], chunk, language_code, app.config["DUGA_USER_AGENT"]
        )
        for qid, info in entities.items():
            if dbname not in info["sitelinks"]:
                missing[qid] = {"label": info["label"]}
    return missing


def run(app=None):
    app = app or create_app(os.environ.get("FLASK_ENV", "production"))
    run_presence_detector(
        app,
        detector_key=DETECTOR_KEY,
        project_code=PROJECT_CODE,
        gap_type=GAP_TYPE,
        maturity="stable",
        description=DESCRIPTION,
        action_url_fn=action_url,
        compute_fn=compute_gaps_for_language,
    )


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- a job must fail loudly, never swallow errors
        print(f"{DETECTOR_KEY} FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
