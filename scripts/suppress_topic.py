"""Operator CLI: suppresses (or un-suppresses) a topic. SPEC.md S4:
suppression is absolute and immediate, filtered at query time everywhere
(app/blueprints/main/routes.py's _visible_gaps_query), and requires no
upstream edit -- just a logged reason. There's no auth'd admin UI for this
yet (that's M4), so it's a script an operator runs by hand on Toolforge,
same pattern as scripts/activate_scope_version.py.

Usage:
    python3 scripts/suppress_topic.py <QID> --reason "..." --by <your-wiki-username>
    python3 scripts/suppress_topic.py <QID> --unsuppress --by <your-wiki-username>
    python3 scripts/suppress_topic.py --list-suppressed
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Topic  # noqa: E402


def list_suppressed():
    topics = Topic.query.filter_by(suppressed=True).order_by(Topic.suppressed_at.desc()).all()
    for topic in topics:
        print(
            f"{topic.qid}\tby={topic.suppressed_by}\tat={topic.suppressed_at}\t"
            f"reason={topic.suppressed_reason!r}"
        )


def suppress(qid, reason, by):
    topic = db.session.get(Topic, qid)
    if topic is None:
        print(f"No topic with qid={qid!r} -- has topic_refresh ever seen it?", file=sys.stderr)
        sys.exit(1)
    topic.suppressed = True
    topic.suppressed_reason = reason
    topic.suppressed_by = by
    topic.suppressed_at = datetime.now(timezone.utc)
    db.session.commit()
    print(f"Suppressed {qid} (by {by!r}): {reason}")


def unsuppress(qid, by):
    topic = db.session.get(Topic, qid)
    if topic is None:
        print(f"No topic with qid={qid!r}", file=sys.stderr)
        sys.exit(1)
    topic.suppressed = False
    topic.suppressed_reason = None
    topic.suppressed_by = None
    topic.suppressed_at = None
    db.session.commit()
    print(f"Un-suppressed {qid} (by {by!r})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("qid", nargs="?", help="Wikidata QID to suppress/un-suppress")
    parser.add_argument("--reason", help="required when suppressing: why this topic is suppressed")
    parser.add_argument("--by", help="your wiki username, recorded as suppressed_by")
    parser.add_argument("--unsuppress", action="store_true", help="lift suppression instead of setting it")
    parser.add_argument(
        "--list-suppressed", action="store_true", help="list currently suppressed topics and exit"
    )
    args = parser.parse_args()

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        if args.list_suppressed:
            list_suppressed()
            return
        if not args.qid or not args.by:
            parser.error("qid and --by are required unless --list-suppressed is given")
        if args.unsuppress:
            unsuppress(args.qid, args.by)
        else:
            if not args.reason:
                parser.error(
                    "--reason is required when suppressing "
                    "(SPEC.md S4: no justification-free suppression)"
                )
            suppress(args.qid, args.reason, args.by)


if __name__ == "__main__":
    main()
