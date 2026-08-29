"""Toolforge job: the vocab_no_term detector -- an in-scope topic with no
local vocabulary term at all in a tracked language (SPEC.md section 11,
post-v0.1). Unlike every other detector so far, this checks Duga's own
`concept`/`term` tables, not Wikidata or a sister project -- "does the
community have a word for this here" is a different question from "does
Wikidata have a label for this."

Scope note: a `concept` can be purely local (`qid IS NULL`) -- SPEC.md
section 10's local -> proposed -> upstream lifecycle -- which doesn't fit
`gap.topic_qid NOT NULL`. This detector only covers concepts that already
have a qid (i.e. are linked to a Topic already in scope); a purely local
concept with no Wikidata item behind it isn't represented as a gap here.
See docs/architecture.md for why this is a deliberate scope decision, not
an oversight.

Ships at maturity 'experimental', disabled by default (see
jobs/detector_common.py's upsert_detector_row) and, per S7, automatically
excludes is_living topics (see run_presence_detector).

Run via: python3 jobs/vocab_no_term.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Concept, Term  # noqa: E402
from jobs.detector_common import chunks, run_presence_detector  # noqa: E402
from jobs.wikimedia_api import MAX_ENTITY_IDS_PER_REQUEST, get_entities_batch  # noqa: E402

DETECTOR_KEY = "vocab_no_term"
PROJECT_CODE = "vocabulary"
GAP_TYPE = "no_term"
DESCRIPTION = "In-scope topic with no local vocabulary term at all in a tracked language."


def action_url(qid: str, language_code: str) -> str:
    # No route accepts a QID/concept to pre-fill the add-term form yet, so
    # this deep-links to the generic per-language add-term form rather
    # than anything topic-specific -- a real if minor UX gap versus every
    # other detector's more targeted destination.
    return f"/{language_code}/vocabulary#add-term-form"


def compute_gaps_for_language(app, language_code, qids):
    """Returns {qid: {"label": str|None}} for in-scope topics with no
    visible local term in `language_code`. The "missing" check is a plain
    local query (no Wikimedia API call needed for it); a label is then
    fetched only for the topics that actually turn out to be missing, so
    the gap row can show a real name instead of a bare QID."""
    covered = {
        row[0]
        for row in db.session.query(Concept.qid)
        .join(Term, Term.concept_id == Concept.id)
        .filter(
            Concept.qid.isnot(None),
            Concept.suppressed.is_(False),
            Term.language_code == language_code,
            Term.suppressed.is_(False),
        )
        .distinct()
        .all()
    }
    missing_qids = [qid for qid in qids if qid not in covered]

    missing = {}
    for chunk in chunks(missing_qids, MAX_ENTITY_IDS_PER_REQUEST):
        entities = get_entities_batch(
            app.config["DUGA_WIKIDATA_API"], chunk, language_code, app.config["DUGA_USER_AGENT"]
        )
        for qid, info in entities.items():
            missing[qid] = {"label": info["label"], "label_lang": info["label_lang"]}
    return missing


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
