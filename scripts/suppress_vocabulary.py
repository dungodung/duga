"""Operator CLI: suppresses (or un-suppresses) a concept or term. SPEC.md
S4: "A suppressed topic or term is filtered at query time in every code
path... Suppression requires no upstream edit and no justification beyond a
logged reason." Unlike `topic`, `concept`/`term` have only a bare
`suppressed` boolean (SPEC.md section 7 -- no dedicated reason/by/at
columns), so the reason and actor are logged to `audit_log` instead
(app/audit.py), which exists as of M4. Same pattern as
scripts/suppress_topic.py otherwise: no auth'd admin UI for this yet.

Usage:
    python3 scripts/suppress_vocabulary.py concept <id> --reason "..." --by <your-wiki-username>
    python3 scripts/suppress_vocabulary.py term <id> --reason "..." --by <your-wiki-username>
    python3 scripts/suppress_vocabulary.py term <id> --unsuppress --by <your-wiki-username>
    python3 scripts/suppress_vocabulary.py --list-suppressed
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.audit import log as audit_log  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Concept, Term  # noqa: E402

MODELS = {"concept": Concept, "term": Term}


def list_suppressed():
    for kind, model in MODELS.items():
        for row in model.query.filter_by(suppressed=True).all():
            label = getattr(row, "local_label", None) or getattr(row, "written_form", None)
            print(f"{kind}\t{row.id}\t{label!r}")


def suppress(kind, item_id, reason, by):
    model = MODELS[kind]
    row = db.session.get(model, item_id)
    if row is None:
        print(f"No {kind} with id={item_id}", file=sys.stderr)
        sys.exit(1)
    row.suppressed = True
    audit_log(
        actor=by,
        action=f"suppress_{kind}",
        entity_type=kind,
        entity_id=item_id,
        before={"suppressed": False},
        after={"suppressed": True, "reason": reason},
    )
    db.session.commit()
    print(f"Suppressed {kind} {item_id} (by {by!r}): {reason}")


def unsuppress(kind, item_id, by):
    model = MODELS[kind]
    row = db.session.get(model, item_id)
    if row is None:
        print(f"No {kind} with id={item_id}", file=sys.stderr)
        sys.exit(1)
    row.suppressed = False
    audit_log(
        actor=by,
        action=f"unsuppress_{kind}",
        entity_type=kind,
        entity_id=item_id,
        before={"suppressed": True},
        after={"suppressed": False},
    )
    db.session.commit()
    print(f"Un-suppressed {kind} {item_id} (by {by!r})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", nargs="?", choices=["concept", "term"])
    parser.add_argument("item_id", nargs="?", type=int)
    parser.add_argument("--reason", help="required when suppressing: why this is suppressed")
    parser.add_argument("--by", help="your wiki username, recorded in audit_log")
    parser.add_argument("--unsuppress", action="store_true", help="lift suppression instead of setting it")
    parser.add_argument("--list-suppressed", action="store_true", help="list suppressed concepts/terms and exit")
    args = parser.parse_args()

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        if args.list_suppressed:
            list_suppressed()
            return
        if not args.kind or not args.item_id or not args.by:
            parser.error("kind, item_id, and --by are required unless --list-suppressed is given")
        if args.unsuppress:
            unsuppress(args.kind, args.item_id, args.by)
        else:
            if not args.reason:
                parser.error(
                    "--reason is required when suppressing "
                    "(SPEC.md S4: no justification-free suppression)"
                )
            suppress(args.kind, args.item_id, args.reason, args.by)


if __name__ == "__main__":
    main()
