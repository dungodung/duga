"""Toolforge job: the wp_no_article detector -- missing Wikipedia articles
for in-scope topics, one gap type in the unifying (topic, language, project,
gap_type, evidence, action, status) record shape (SPEC.md section 1, 11).
v0.1 detector, maturity 'stable'.

Run via: python3 jobs/wp_no_article.py
Idempotent (SPEC.md guardrail 8): fully replaces this detector's gap rows
for each seeded language on every successful run. A failed run leaves
existing gap rows untouched and marks detector.last_status so the UI can
show staleness rather than silently serving old data as current
(guardrail 9) -- results are collected in memory first and only written in
one transaction if every language's data fetched cleanly.

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

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Detector, Gap, Language, ScopeVersion, Topic  # noqa: E402
from jobs.wikimedia_api import (  # noqa: E402
    MAX_ENTITY_IDS_PER_REQUEST,
    WikimediaApiError,
    get_entities_batch,
)

DETECTOR_KEY = "wp_no_article"
PROJECT_CODE = "wikipedia"
GAP_TYPE = "no_article"

# Wikipedia site-key exceptions where it isn't simply f"{code}wiki" --
# extend as new seeded languages hit one (SPEC.md section 13: Wikimedia
# language codes, not ISO, and Wikipedia's own db-name convention has its
# own historical quirks on top of that).
WIKIPEDIA_DBNAME_OVERRIDES = {
    "nb": "nowiki",
}


def wikipedia_dbname(language_code: str) -> str:
    return WIKIPEDIA_DBNAME_OVERRIDES.get(language_code, f"{language_code}wiki")


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def compute_gaps_for_language(app, language, qids):
    """Returns {qid: label_or_None} for topics with no Wikipedia article in
    `language`. Raises WikimediaApiError on any batch failure."""
    dbname = wikipedia_dbname(language.code)
    missing = {}
    for chunk in _chunks(qids, MAX_ENTITY_IDS_PER_REQUEST):
        entities = get_entities_batch(
            app.config["DUGA_WIKIDATA_API"], chunk, language.code, app.config["DUGA_USER_AGENT"]
        )
        for qid, info in entities.items():
            if dbname not in info["sitelinks"]:
                missing[qid] = info["label"]
    return missing


def _upsert_detector_row(status):
    detector = Detector.query.filter_by(detector_key=DETECTOR_KEY).first()
    if detector is None:
        detector = Detector(
            detector_key=DETECTOR_KEY,
            project_code=PROJECT_CODE,
            gap_type=GAP_TYPE,
            maturity="stable",
            enabled=True,
            description="Missing Wikipedia article in a tracked language for an in-scope topic.",
        )
        db.session.add(detector)
    detector.last_run_at = datetime.now(timezone.utc)
    detector.last_status = status


def run(app=None):
    app = app or create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        active_version = ScopeVersion.query.filter_by(active=True).first()
        if active_version is None:
            print(f"{DETECTOR_KEY}: no active scope_version -- nothing to do", file=sys.stderr)
            sys.exit(1)

        languages = Language.query.filter_by(seeded=True).all()
        if not languages:
            print(f"{DETECTOR_KEY}: no seeded languages -- nothing to do", file=sys.stderr)
            sys.exit(1)

        qids = [row[0] for row in Topic.query.filter_by(suppressed=False).with_entities(Topic.qid).all()]

        results = {}  # language_code -> {qid: label_or_None}
        try:
            for language in languages:
                results[language.code] = compute_gaps_for_language(app, language, qids)
        except WikimediaApiError as exc:
            print(f"{DETECTOR_KEY} FAILED: {exc}", file=sys.stderr)
            _upsert_detector_row("error")
            db.session.commit()
            sys.exit(1)

        now = datetime.now(timezone.utc)
        for language_code, missing in results.items():
            Gap.query.filter_by(
                detector_key=DETECTOR_KEY,
                language_code=language_code,
                project_code=PROJECT_CODE,
                gap_type=GAP_TYPE,
            ).delete()
            for qid, label in missing.items():
                db.session.add(
                    Gap(
                        topic_qid=qid,
                        language_code=language_code,
                        project_code=PROJECT_CODE,
                        gap_type=GAP_TYPE,
                        detector_key=DETECTOR_KEY,
                        scope_version_id=active_version.id,
                        evidence_json=json.dumps({"label": label}),
                        action_url=f"https://www.wikidata.org/wiki/{qid}#sitelinks-wikipedia",
                        computed_at=now,
                    )
                )

        _upsert_detector_row("ok")
        db.session.commit()

        total = sum(len(m) for m in results.values())
        print(f"{DETECTOR_KEY}: {total} gaps across {len(languages)} language(s), {len(qids)} topics checked")


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- a job must fail loudly, never swallow errors
        print(f"{DETECTOR_KEY} FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
