"""Toolforge job: the wd_no_label detector -- in-scope Wikidata items with
no label in a tracked language, one gap type in the unifying (topic,
language, project, gap_type, evidence, action, status) record shape
(SPEC.md section 1, 11). v0.1 detector, maturity 'stable'.

Run via: python3 jobs/wd_no_label.py
Idempotent (SPEC.md guardrail 8) and fails loudly (guardrail 9) -- see
jobs/detector_common.py's run_presence_detector for the shared mechanics
every "is X missing" detector uses.

Uses jobs/wikimedia_api.py's get_raw_labels_and_descriptions, not
get_entities_batch: this detector needs to know whether a label is *really*
absent in the language being checked, so it must not use MediaWiki's
language-fallback chain (which would paper over a genuine gap with a
borrowed label from a related language).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from jobs.detector_common import chunks, run_presence_detector  # noqa: E402
from jobs.wikimedia_api import MAX_ENTITY_IDS_PER_REQUEST, get_raw_labels_and_descriptions  # noqa: E402

DETECTOR_KEY = "wd_no_label"
PROJECT_CODE = "wikidata"
GAP_TYPE = "no_label"
DESCRIPTION = "No Wikidata label in a tracked language for an in-scope topic."


def action_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}#labels"


def compute_gaps_for_language(app, language_code, qids):
    """Returns {qid: {"label": str|None}} for topics with no genuine
    Wikidata label in `language_code`. The "label" evidence value is an
    English fallback purely for display on the gap list -- it is not what
    is missing here, since English isn't the tracked language."""
    missing = {}
    for chunk in chunks(qids, MAX_ENTITY_IDS_PER_REQUEST):
        data = get_raw_labels_and_descriptions(
            app.config["DUGA_WIKIDATA_API"], chunk, language_code, app.config["DUGA_USER_AGENT"]
        )
        for qid, info in data.items():
            if not info["label_language"]:
                missing[qid] = {"label": info["label_en"]}
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
