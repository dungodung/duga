"""Toolforge job: the wikisource_no_text detector -- missing Wikisource
pages for in-scope topics (SPEC.md section 11, post-v0.1). Ships at
maturity 'experimental', disabled by default (see
jobs/detector_common.py's upsert_detector_row) and, per S7, automatically
excludes is_living topics (see run_presence_detector).

Run via: python3 jobs/wikisource_no_text.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from jobs.detector_common import run_presence_detector  # noqa: E402
from jobs.sitelink_gap import make_compute_fn  # noqa: E402

DETECTOR_KEY = "wikisource_no_text"
PROJECT_CODE = "wikisource"
GAP_TYPE = "no_text"
FAMILY = "wikisource"
DESCRIPTION = "Missing Wikisource page in a tracked language for an in-scope topic."


def action_url(qid: str, language_code: str) -> str:
    # This detector's destination is on Wikidata, same URL for every
    # language -- language_code is part of the shared action_url_fn
    # signature (see jobs/detector_common.py) but unused here.
    return f"https://www.wikidata.org/wiki/{qid}#sitelinks-wikisource"


def run(app=None):
    app = app or create_app(os.environ.get("FLASK_ENV", "production"))
    run_presence_detector(
        app,
        detector_key=DETECTOR_KEY,
        project_code=PROJECT_CODE,
        gap_type=GAP_TYPE,
        maturity="experimental",
        description=DESCRIPTION,
        action_url_fn=action_url,
        compute_fn=make_compute_fn(FAMILY),
    )


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- a job must fail loudly, never swallow errors
        print(f"{DETECTOR_KEY} FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
