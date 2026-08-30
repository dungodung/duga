"""Shared plumbing for gap-detector jobs (SPEC.md section 11). Every
"is X missing for this (topic, language)" detector -- wp_no_article.py,
wd_no_label.py, wd_no_description.py -- has identical control flow around a
detector-specific compute step: check for an active scope version and
seeded languages, release the DB connection before the slow Wikimedia API
work, then replace this detector's gap rows.

**The unit of work is one language.** Each is computed, written and
committed on its own, so a failure part-way through a ten-language sweep
keeps the languages that already succeeded instead of discarding the lot.
Atomicity is preserved where it actually matters -- replace_gaps() deletes
and reinserts one (detector, language) at a time, so a language's gap list
is never half-written -- and any failure still marks the detector `error`
and exits non-zero, so the UI shows it as stale rather than serving old
rows as current (SPEC.md guardrail 9).
"""
import argparse
import sys
from datetime import datetime, timezone
import json

from app.extensions import db
from app.models import Detector, Gap, Language, ScopeVersion, Topic
from jobs.wikimedia_api import WikimediaApiError


def _requested_languages():
    """`--languages de,en` -> {"de", "en"}; empty when not given. Parsed
    permissively so a detector can still be run with no arguments at all,
    which is how the scheduled jobs invoke it."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--languages", default="")
    args, _unknown = parser.parse_known_args()
    return {code.strip() for code in args.languages.split(",") if code.strip()}


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
    Returns the total number of gap rows written.

    action_url_fn(qid, language_code) supplies the default action_url for
    a gap row. A compute_fn that already knows a more specific destination
    than the shared function can produce (e.g. vocab_no_evidence linking
    straight to one term's detail page, not just the language's generic
    vocabulary list) can set evidence["_action_url"] instead -- it's used
    in place of action_url_fn and stripped before evidence_json is stored,
    so it never leaks into what's displayed as evidence."""
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
            action_url = evidence.pop("_action_url", None) or action_url_fn(qid, language_code)
            db.session.add(
                Gap(
                    topic_qid=qid,
                    language_code=language_code,
                    project_code=project_code,
                    gap_type=gap_type,
                    detector_key=detector_key,
                    scope_version_id=active_version_id,
                    evidence_json=json.dumps(evidence),
                    action_url=action_url,
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
    shared. Exits the process (sys.exit(1)) if any language failed,
    matching SPEC.md guardrail 9 (fail loudly, never serve stale data as
    current without saying so) -- after finishing the languages that can
    still be done, and after recording the failure on the detector row.

    action_url_fn(qid, language_code) -> str; see replace_gaps() for the
    per-gap evidence["_action_url"] override a compute_fn can use instead.

    compute_fn isn't required to call an external API at all -- a purely
    local-DB detector (vocab_no_term, vocab_no_evidence) works fine too,
    since closing db.session before the loop (below) only releases the
    current connection, it doesn't stop compute_fn from issuing new
    queries; SQLAlchemy just checks out a fresh one lazily."""
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

        # `--languages de,en` runs a subset. Detectors are chunked by
        # language anyway (see the loop below); this is the manual lever for
        # re-running just the language that failed, without redoing the
        # nine that didn't.
        wanted = _requested_languages()
        if wanted:
            unknown = [code for code in wanted if code not in language_codes]
            if unknown:
                print(f"{detector_key}: not seeded content languages: {unknown}", file=sys.stderr)
                sys.exit(1)
            language_codes = [code for code in language_codes if code in wanted]

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

        # One language at a time, committed as it goes. A sweep is ~220 API
        # requests per language, so ten languages is a ~13-minute run -- and
        # when a single request failed thirteen minutes in (wp_no_article,
        # 2026-08-30), the old all-or-nothing shape threw away every
        # language's work. The atomic unit that matters is still preserved:
        # replace_gaps() deletes and reinserts one (detector, language) at a
        # time, so a language's list is never half-written. What changes is
        # that a bad language no longer costs the good ones.
        total = 0
        failures = {}
        for language_code in language_codes:
            try:
                results = {language_code: compute_fn(app, language_code, qids)}
                total += replace_gaps(
                    detector_key, project_code, gap_type, results, active_version_id, action_url_fn
                )
                db.session.commit()
            except Exception as exc:  # noqa: BLE001 -- see the comment below
                # Deliberately broad. The previous handler caught only
                # WikimediaApiError, so a connection reset (a plain
                # requests.RequestException) escaped it, the detector row was
                # never marked, and the UI kept serving the previous day's
                # gaps as current -- the exact failure guardrail 9 forbids.
                # Network errors are now typed properly too
                # (jobs/wikimedia_api.py:_get), but the handler stays broad:
                # anything that can end a run must still end it loudly.
                db.session.rollback()
                failures[language_code] = f"{exc.__class__.__name__}: {exc}"
                print(f"{detector_key}: {language_code} FAILED: {exc}", file=sys.stderr)

        # Marked before the exit, and in its own transaction, so the row
        # reflects reality even when the run died mid-write.
        status = "error" if failures else "ok"
        try:
            upsert_detector_row(detector_key, project_code, gap_type, maturity, description, status)
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            print(f"{detector_key}: could not record status {status!r}: {exc}", file=sys.stderr)

        done = len(language_codes) - len(failures)
        print(
            f"{detector_key}: {total} gaps across {done}/{len(language_codes)} language(s), "
            f"{len(qids)} topics checked"
        )
        if failures:
            print(f"{detector_key} FAILED for {sorted(failures)}", file=sys.stderr)
            sys.exit(1)
