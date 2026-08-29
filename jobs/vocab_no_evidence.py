"""Toolforge job: the vocab_no_evidence detector -- a local vocabulary
term with no evidence at all (SPEC.md section 11, post-v0.1; SPEC.md
section 8's evidence_grade only reaches above 'single_report' once at
least one term_evidence row or community assertion exists -- this flags
the case where there isn't even one).

Purely a local-DB detector, same as vocab_no_term.py and same qid-scoping
note applies: only terms whose concept already has a qid are covered
(see vocab_no_term.py's docstring and docs/architecture.md).

A concept can have more than one term in the same language (different
written forms of the same idea) -- the gap table has no per-term column,
only (topic_qid, language_code, project_code, gap_type), so this flags
the (topic, language) pair if *any* visible term of that concept in that
language currently has zero evidence, deterministically picking the
lowest-id such term to name in the gap row and to deep-link to. That's
the more actionable reading (guardrail 12's "when in doubt, show less"
is about sensitive display decisions, not about hiding a real, ordinary
maintenance need) -- but if a concept has several under-evidenced terms
in one language, only one is directly linked to at a time, so a second
"no_evidence" gap doesn't appear here until the linked-to term gets its
first citation.

Ships at maturity 'experimental', disabled by default (see
jobs/detector_common.py's upsert_detector_row) and, per S7, automatically
excludes is_living topics (see run_presence_detector).

Run via: python3 jobs/vocab_no_evidence.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Concept, Term, TermEvidence  # noqa: E402
from jobs.detector_common import run_presence_detector  # noqa: E402

DETECTOR_KEY = "vocab_no_evidence"
PROJECT_CODE = "vocabulary"
GAP_TYPE = "no_evidence"
DESCRIPTION = "Local vocabulary term for an in-scope topic with no evidence at all."


def action_url(qid: str, language_code: str) -> str:
    # Fallback only -- compute_gaps_for_language always sets a term-
    # specific evidence["_action_url"] (see jobs/detector_common.py's
    # replace_gaps), since it already knows exactly which term to link to.
    return f"/{language_code}/vocabulary"


def compute_gaps_for_language(app, language_code, qids):
    """Returns {qid: {"label": written_form, "_action_url": ...}} for
    in-scope topics with at least one visible local term in
    `language_code` that has zero term_evidence rows. No Wikimedia API
    call at all -- the term's own written form is a more useful label
    here than the topic's Wikidata label would be, since it's the actual
    thing that needs a source."""
    qids_in_scope = set(qids)
    rows = (
        db.session.query(Concept.qid, Term.id, Term.written_form)
        .join(Term, Term.concept_id == Concept.id)
        .outerjoin(TermEvidence, TermEvidence.term_id == Term.id)
        .filter(
            Concept.qid.isnot(None),
            Concept.suppressed.is_(False),
            Term.language_code == language_code,
            Term.suppressed.is_(False),
            TermEvidence.id.is_(None),
        )
        .order_by(Term.id)
        .all()
    )

    missing = {}
    for qid, term_id, written_form in rows:
        if qid not in qids_in_scope or qid in missing:
            continue  # keep the lowest-id under-evidenced term per (topic, language)
        missing[qid] = {
            "label": written_form,
            # Unlike every other detector, the label here is Duga's own
            # term, so its language is known exactly rather than inferred
            # from what Wikidata happened to return.
            "label_lang": language_code,
            "_action_url": f"/{language_code}/vocabulary/{term_id}#add-evidence-form",
        }
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
