"""Operator CLI: records a human decision about one specific gap
(declined / not_applicable / done) so a detector's next run can never
silently re-surface or destroy it (SPEC.md section 7 -- "human decisions
live separately so recomputation never destroys them"; guardrail 5).
No auth'd UI for self-service overrides yet (that's the real
POST /gap/override endpoint, M4) -- this is the operator-driven stand-in,
same pattern as scripts/activate_scope_version.py and
scripts/suppress_topic.py. An override hides its gap immediately
(app/blueprints/main/routes.py's _visible_gaps_query), regardless of status.

Usage:
    python3 scripts/set_gap_override.py <QID> <language> <project> <gap_type> \\
        --status done --by <your-wiki-username> [--reason "..."]
    python3 scripts/set_gap_override.py --list
    python3 scripts/set_gap_override.py --clear <QID> <language> <project> <gap_type>
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import GapOverride  # noqa: E402

VALID_STATUSES = ("declined", "not_applicable", "done")


def list_overrides():
    for o in GapOverride.query.order_by(GapOverride.set_at.desc()).all():
        print(
            f"{o.topic_qid}\t{o.language_code}\t{o.project_code}\t{o.gap_type}\t"
            f"{o.status}\tby={o.set_by}\tat={o.set_at}\treason={o.reason!r}"
        )


def set_override(qid, language, project, gap_type, status, by, reason):
    existing = GapOverride.query.filter_by(
        topic_qid=qid, language_code=language, project_code=project, gap_type=gap_type
    ).first()
    if existing is None:
        existing = GapOverride(
            topic_qid=qid, language_code=language, project_code=project, gap_type=gap_type
        )
        db.session.add(existing)
    existing.status = status
    existing.reason = reason
    existing.set_by = by
    existing.set_at = datetime.now(timezone.utc)
    db.session.commit()
    print(f"Set override: {qid} {language} {project} {gap_type} -> {status} (by {by!r})")


def clear_override(qid, language, project, gap_type):
    deleted = GapOverride.query.filter_by(
        topic_qid=qid, language_code=language, project_code=project, gap_type=gap_type
    ).delete()
    db.session.commit()
    if deleted:
        print(f"Cleared override: {qid} {language} {project} {gap_type}")
    else:
        print(f"No override existed for: {qid} {language} {project} {gap_type}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("qid", nargs="?")
    parser.add_argument("language", nargs="?")
    parser.add_argument("project", nargs="?")
    parser.add_argument("gap_type", nargs="?")
    parser.add_argument("--status", choices=VALID_STATUSES)
    parser.add_argument("--by", help="your wiki username, recorded as set_by")
    parser.add_argument("--reason", help="optional: why this decision was made")
    parser.add_argument("--list", action="store_true", help="list all overrides and exit")
    parser.add_argument("--clear", action="store_true", help="remove the override instead of setting one")
    args = parser.parse_args()

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        if args.list:
            list_overrides()
            return
        if not all([args.qid, args.language, args.project, args.gap_type]):
            parser.error("qid, language, project, and gap_type are required unless --list is given")
        if args.clear:
            clear_override(args.qid, args.language, args.project, args.gap_type)
            return
        if not args.status or not args.by:
            parser.error("--status and --by are required when setting an override")
        set_override(args.qid, args.language, args.project, args.gap_type, args.status, args.by, args.reason)


if __name__ == "__main__":
    main()
