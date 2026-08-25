"""Shared plumbing for gap-detector jobs (SPEC.md section 11). Every
"is X missing for this (topic, language)" detector -- wp_no_article.py,
wd_no_label.py, wd_no_description.py -- has identical control flow around a
detector-specific compute step: check for an active scope version and
seeded languages, release the DB connection before a slow multi-minute
Wikimedia API loop, then atomically replace this detector's gap rows (or
leave them untouched and mark the detector as errored, never partially
written -- SPEC.md guardrail 9).
"""
import sys
from datetime import datetime, timezone
import json

from app.extensions import db
from app.models import Detector, Gap, Language, ScopeVersion, Topic
from jobs.wikimedia_api import WikimediaApiError


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_detector_row(detector_key, project_code, gap_type, maturity, description, status):
    detector = Detector.query.filter_by(detector_key=detector_key).first()
    if detector is None:
        detector = Detector(
            detector_key=detector_key,
            project_code=project_code,
            gap_type=gap_type,
            maturity=maturity,
            # SPEC.md section 11: post-v0.1 detectors ship "behind
            # maturity='experimental', disabled by default" -- promotion to
            # enabled is then a human decision, not something a job grants
            # itself on creation.
            enabled=(maturity != "experimental"),
            description=description,
        )
        db.session.add(detector)
    detector.last_run_at = datetime.now(timezone.utc)
    detector.last_status = status
    return detector


def replace_gaps(detector_key, project_code, gap_type, results, active_version_id, action_url_fn):
    """results: {language_code: {qid: evidence_dict}}. Fully replaces this
    detector's gap rows for every language present in `results` -- SPEC.md
    guardrail 8 (idempotent jobs): a topic no longer in `results[lang]`
    simply isn't re-inserted, so it drops out of the gap list on this run.
    Returns the total number of gap rows written."""
    now = datetime.now(timezone.utc)
    total = 0
    for language_code, missing in results.items():
        Gap.query.filter_by(
            detector_key=detector_key,
            language_code=language_code,
            project_code=project_code,
            gap_type=gap_type,
        ).delete()
        for qid, evidence in missing.items():
            db.session.add(
                Gap(
                    topic_qid=qid,
                    language_code=language_code,
                    project_code=project_code,
                    gap_type=gap_type,
                    detector_key=detector_key,
                    scope_version_id=active_version_id,
                    evidence_json=json.dumps(evidence),
                    action_url=action_url_fn(qid),
                    computed_at=now,
                )
            )
            total += 1
    return total


def run_presence_detector(
    app, *, detector_key, project_code, gap_type, maturity, description, action_url_fn, compute_fn
):
    """Generic runner for a "is X missing per (topic, language)" detector.
    compute_fn(app, language_code, qids) -> {qid: evidence_dict}, raising
    WikimediaApiError on failure -- everything else (guard clauses,
    releasing the DB connection before the slow loop, the atomic
    replace-or-leave-untouched write, detector self-registration) is
    shared. Exits the process (sys.exit(1)) on any failure condition,
    matching SPEC.md guardrail 9 (fail loudly, never serve stale data as
    current without saying so)."""
    with app.app_context():
        active_version = ScopeVersion.query.filter_by(active=True).first()
        if active_version is None:
            print(f"{detector_key}: no active scope_version -- nothing to do", file=sys.stderr)
            sys.exit(1)
        active_version_id = active_version.id

        languages = Language.query.filter_by(seeded=True).all()
        if not languages:
            print(f"{detector_key}: no seeded languages -- nothing to do", file=sys.stderr)
            sys.exit(1)
        language_codes = [language.code for language in languages]

        topic_query = Topic.query.filter_by(suppressed=False)
        if maturity == "experimental":
            # SPEC.md section 11 / S7: experimental detectors exclude
            # living topics, enforced centrally here rather than trusting
            # each new detector file to remember it individually -- the
            # same reasoning as wikidata_write.py enforcing S1 structurally
            # instead of per-call-site discipline.
            topic_query = topic_query.filter_by(is_living=False)
        qids = [row[0] for row in topic_query.with_entities(Topic.qid).all()]

        # Release the DB connection before the slow part -- see
        # jobs/wp_no_article.py's original fix notes: holding a connection
        # checked out on an open transaction across a multi-minute API loop
        # produced "MySQL server has gone away" against ToolsDB in
        # production. pool_pre_ping/pool_recycle only get a chance to act
        # at checkout, and nothing gets checked back in while a transaction
        # stays open across the loop.
        db.session.close()

        results = {}  # language_code -> {qid: evidence_dict}
        try:
            for language_code in language_codes:
                results[language_code] = compute_fn(app, language_code, qids)
        except WikimediaApiError as exc:
            print(f"{detector_key} FAILED: {exc}", file=sys.stderr)
            upsert_detector_row(detector_key, project_code, gap_type, maturity, description, "error")
            db.session.commit()
            sys.exit(1)

        total = replace_gaps(detector_key, project_code, gap_type, results, active_version_id, action_url_fn)
        upsert_detector_row(detector_key, project_code, gap_type, maturity, description, "ok")
        db.session.commit()

        print(f"{detector_key}: {total} gaps across {len(languages)} language(s), {len(qids)} topics checked")
